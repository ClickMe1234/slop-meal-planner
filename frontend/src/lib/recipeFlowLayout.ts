import type {
  BackendMethodAction,
  BackendMethodDocument,
  BackendMethodTableDocument,
} from '../api/client'

export interface FlowRow {
  id: string
  kind: 'ingredient' | 'setup'
  bindingId?: string
  ingredientLineageId?: string
  actionId?: string
  label: string
}

export interface FlowColumn {
  actionId: string
  stageId: string
  stageTitle: string
  index: number
  label: string
}

export interface FlowCell {
  actionId: string
  column: number
  rowStart: number
  rowSpan: number
  inputBindingIds: string[]
  predecessorActionIds: string[]
  kind: 'operation' | 'setup' | 'merge'
}

export interface FlowConnector {
  edgeId: string
  kind: 'sequence' | 'merge' | 'fork'
  fromActionId: string
  toActionId: string
  fromRow: number
  toRow: number
  column: number
}

export interface FlowLane {
  stageId: string
  title: string
  startColumn: number
  endColumn: number
}

export interface FlowRenderWarning {
  code: string
  message: string
  blocking: boolean
  entityId?: string
}

export interface FlowTableLayout {
  rows: FlowRow[]
  columns: FlowColumn[]
  cells: FlowCell[]
  connectors: FlowConnector[]
  lanes: FlowLane[]
  warnings: FlowRenderWarning[]
}

const threshold = .65

function actionSortKey(action: BackendMethodAction) {
  return `${String(action.position).padStart(8, '0')}:${action.id}`
}

function overlap(left: { rowStart: number; rowSpan: number }, right: { rowStart: number; rowSpan: number }) {
  return left.rowStart < right.rowStart + right.rowSpan && right.rowStart < left.rowStart + left.rowSpan
}

function topologicalActions(method: BackendMethodDocument, warnings: FlowRenderWarning[]) {
  const actions = new Map(method.actions.map(action => [action.id, action]))
  const incoming = new Map<string, string[]>(method.actions.map(action => [action.id, []]))
  const outgoing = new Map<string, string[]>(method.actions.map(action => [action.id, []]))
  for (const edge of method.edges) {
    if (!actions.has(edge.from_action_id) || !actions.has(edge.to_action_id)) {
      warnings.push({ code: 'dangling_edge', message: 'A flow connector points to an operation that no longer exists.', blocking: true, entityId: edge.id })
      continue
    }
    incoming.get(edge.to_action_id)!.push(edge.from_action_id)
    outgoing.get(edge.from_action_id)!.push(edge.to_action_id)
  }
  const indegree = new Map([...incoming].map(([id, parents]) => [id, parents.length]))
  const queue = method.actions.filter(action => indegree.get(action.id) === 0).sort((a, b) => actionSortKey(a).localeCompare(actionSortKey(b)))
  const order: string[] = []
  while (queue.length) {
    const next = queue.shift()!
    order.push(next.id)
    for (const childId of [...(outgoing.get(next.id) ?? [])].sort((left, right) => actionSortKey(actions.get(left)!).localeCompare(actionSortKey(actions.get(right)!)))) {
      const nextDegree = (indegree.get(childId) ?? 0) - 1
      indegree.set(childId, nextDegree)
      if (nextDegree === 0) {
        queue.push(actions.get(childId)!)
        queue.sort((a, b) => actionSortKey(a).localeCompare(actionSortKey(b)))
      }
    }
  }
  if (order.length !== method.actions.length) {
    warnings.push({ code: 'graph_cycle', message: 'This flow contains a cycle; connectors are shown in source order until it is repaired.', blocking: true })
    for (const action of [...method.actions].sort((a, b) => actionSortKey(a).localeCompare(actionSortKey(b)))) {
      if (!order.includes(action.id)) order.push(action.id)
    }
  }
  return { order, incoming, outgoing, actions }
}

export function createFlowTableLayout(method: BackendMethodDocument, table?: BackendMethodTableDocument): FlowTableLayout {
  const savedTable = table ?? {
    schema_version: 1 as const,
    labels: [],
    row_order: [],
    column_hints: [],
    setup_action_ids: [],
    terminal_action_ids: [],
    omissions: [],
  }
  const warnings: FlowRenderWarning[] = []
  const { order, incoming, outgoing, actions } = topologicalActions(method, warnings)
  const inputBindings = method.ingredient_bindings.filter(binding => binding.role !== 'reference')
  const bindingById = new Map(inputBindings.map(binding => [binding.id, binding]))
  const rows: FlowRow[] = []
  const setupIds = new Set(savedTable.setup_action_ids.filter(actionId => actions.has(actionId)))
  for (const actionId of order) {
    if (setupIds.has(actionId)) rows.push({ id: `setup:${actionId}`, kind: 'setup', actionId, label: 'Setup' })
  }
  const savedRows = savedTable.row_order.filter(bindingId => bindingById.has(bindingId))
  const rowIds = [...savedRows, ...inputBindings.map(binding => binding.id).filter(bindingId => !savedRows.includes(bindingId))]
  for (const bindingId of rowIds) {
    const binding = bindingById.get(bindingId)!
    rows.push({ id: `binding:${binding.id}`, kind: 'ingredient', bindingId: binding.id, ingredientLineageId: binding.ingredient_lineage_id, label: binding.ingredient_lineage_id })
  }
  if (!rows.length && order.length) rows.push({ id: 'setup:default', kind: 'setup', label: 'Flow' })

  const rowIndex = new Map(rows.map((row, index) => [row.id, index]))
  const labels = new Map(savedTable.labels.map(label => [label.action_id, label]))
  for (const action of method.actions) {
    const label = labels.get(action.id)
    if (!label) warnings.push({ code: 'missing_label', message: 'An operation is missing a compact table label.', blocking: true, entityId: action.id })
    if (label && label.confidence < threshold && label.accepted !== true) warnings.push({ code: 'low_confidence_label', message: 'An operation label is uncertain.', blocking: true, entityId: action.id })
  }
  for (const binding of inputBindings) {
    if (binding.confidence < threshold && binding.accepted !== true) warnings.push({ code: 'low_confidence_binding', message: 'An ingredient placement is uncertain.', blocking: true, entityId: binding.id })
  }
  for (const edge of method.edges) {
    if (edge.confidence < threshold && edge.accepted !== true) warnings.push({ code: 'low_confidence_edge', message: 'A branch connection is uncertain.', blocking: true, entityId: edge.id })
  }

  const cellsByAction = new Map<string, FlowCell>()
  const logicalColumns = new Map<string, number>()
  const occupied = new Map<number, FlowCell[]>()
  const hints = new Map(savedTable.column_hints.map(hint => [hint.action_id, hint.preferred_column]))
  const rowRangeForAction = (actionId: string) => {
    const directRows = inputBindings
      .filter(binding => binding.action_id === actionId)
      .map(binding => rowIndex.get(`binding:${binding.id}`))
      .filter((index): index is number => index != null)
    const predecessorRows = (incoming.get(actionId) ?? [])
      .map(parentId => cellsByAction.get(parentId))
      .filter((cell): cell is FlowCell => Boolean(cell))
      .flatMap(cell => Array.from({ length: cell.rowSpan }, (_, offset) => cell.rowStart + offset))
    const values = [...directRows, ...predecessorRows]
    if (!values.length) {
      const setup = rowIndex.get(`setup:${actionId}`)
      return { rowStart: setup ?? 0, rowSpan: 1 }
    }
    const rowStart = Math.min(...values)
    return { rowStart, rowSpan: Math.max(...values) - rowStart + 1 }
  }
  for (const actionId of order) {
    const action = actions.get(actionId)!
    const parents = incoming.get(actionId) ?? []
    const earliest = parents.length ? Math.max(...parents.map(parentId => (logicalColumns.get(parentId) ?? 0) + 1)) : 0
    let logicalColumn = Math.max(earliest, hints.get(actionId) ?? 0)
    const range = rowRangeForAction(actionId)
    while ((occupied.get(logicalColumn) ?? []).some(cell => overlap(cell, range))) logicalColumn += 1
    const cell: FlowCell = {
      actionId,
      column: logicalColumn,
      rowStart: range.rowStart,
      rowSpan: range.rowSpan,
      inputBindingIds: inputBindings.filter(binding => binding.action_id === actionId).map(binding => binding.id),
      predecessorActionIds: parents,
      kind: parents.length > 1 ? 'merge' : setupIds.has(actionId) ? 'setup' : 'operation',
    }
    cellsByAction.set(actionId, cell)
    logicalColumns.set(actionId, logicalColumn)
    occupied.set(logicalColumn, [...(occupied.get(logicalColumn) ?? []), cell])
  }
  const logicalColumnValues = [...new Set([...logicalColumns.values()])].sort((a, b) => a - b)
  const columnIndex = new Map(logicalColumnValues.map((value, index) => [value, index]))
  const labelsByAction = new Map(savedTable.labels.map(label => [label.action_id, label.text]))
  const columns: FlowColumn[] = logicalColumnValues.map((logical, index) => {
    const actionId = order.find(id => logicalColumns.get(id) === logical)!
    const action = actions.get(actionId)!
    const stage = method.stages.find(item => item.id === action.stage_id)
    return { actionId, stageId: action.stage_id, stageTitle: stage?.title ?? 'Method', index, label: labelsByAction.get(actionId) ?? action.text }
  })
  const cells = [...cellsByAction.values()].map(cell => ({ ...cell, column: columnIndex.get(cell.column) ?? cell.column }))
  const connectors: FlowConnector[] = method.edges.flatMap(edge => {
    const from = cellsByAction.get(edge.from_action_id)
    const to = cellsByAction.get(edge.to_action_id)
    if (!from || !to) return []
    const fanIn = (incoming.get(edge.to_action_id) ?? []).length > 1
    const fanOut = (outgoing.get(edge.from_action_id) ?? []).length > 1
    return [{
      edgeId: edge.id,
      kind: fanIn ? 'merge' : fanOut ? 'fork' : edge.kind,
      fromActionId: edge.from_action_id,
      toActionId: edge.to_action_id,
      fromRow: from.rowStart,
      toRow: to.rowStart,
      column: Math.max(0, (columnIndex.get(to.column) ?? to.column) - 1),
    }]
  })
  const lanes: FlowLane[] = []
  for (const column of columns) {
    const last = lanes[lanes.length - 1]
    if (last?.stageId === column.stageId) last.endColumn = column.index
    else lanes.push({ stageId: column.stageId, title: column.stageTitle, startColumn: column.index, endColumn: column.index })
  }
  return { rows, columns, cells, connectors, lanes, warnings }
}
