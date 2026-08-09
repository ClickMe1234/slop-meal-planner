import { useDraggable, useDroppable } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowDown, ArrowUp, Check, ChevronLeft, ChevronRight, Clock3, GripVertical, Layers3, Link2, Thermometer, Utensils, WandSparkles, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import type {
  BackendMethodAction,
  BackendMethodDocument,
  BackendMethodIngredient,
  BackendMethodTableDocument,
  BackendMethodTableIngredientUse,
  BackendMethodTableWarning,
  BackendMethodView,
} from '../api/client'
import { Badge, Button, Card } from './ui'
import { createFlowTableLayout, type FlowCell, type FlowRow } from '../lib/recipeFlowLayout'

export const emptyTableDocument = (): BackendMethodTableDocument => ({
  schema_version: 1,
  labels: [],
  row_order: [],
  column_hints: [],
  setup_action_ids: [],
  terminal_action_ids: [],
  omissions: [],
})

interface RecipeFlowTableProps {
  data: BackendMethodView
  method: BackendMethodDocument
  table: BackendMethodTableDocument
  editable?: boolean
  onTableChange?: (table: BackendMethodTableDocument) => void
  onMethodChange?: (method: BackendMethodDocument) => void
  onSelectAction?: (actionId: string) => void
}

function warningTone(warning: BackendMethodTableWarning) {
  return warning.blocking ? 'warning' : 'info'
}

function ActionMeta({ action }: { action: BackendMethodAction }) {
  return <div className="flow-operation-meta">
    {action.duration_text && <span><Clock3 size={13}/>{action.duration_text}</span>}
    {!action.duration_text && action.duration_minutes != null && <span><Clock3 size={13}/>{action.duration_minutes} min</span>}
    {action.temperature_value != null && <span><Thermometer size={13}/>{action.temperature_value}°{action.temperature_unit?.toUpperCase()}</span>}
    {action.equipment.slice(0, 2).map(item => <span key={item}><Utensils size={13}/>{item}</span>)}
    {action.cue && <span><Check size={13}/>{action.cue}</span>}
  </div>
}

function OperationCell({
  action,
  cell,
  label,
  uses,
  editable,
  onLabelChange,
  onDisconnect,
  onSelect,
}: {
  action: BackendMethodAction
  cell: FlowCell
  label: string
  uses: BackendMethodTableIngredientUse[]
  editable: boolean
  onLabelChange: (value: string) => void
  onDisconnect?: (bindingId: string) => void
  onSelect: () => void
}) {
  const drop = useDroppable({ id: `flow-action:${action.id}`, data: { type: 'flow-action', actionId: action.id } })
  const drag = useDraggable({ id: `flow-action:${action.id}`, disabled: !editable, data: { type: 'flow-action', label: action.text, actionId: action.id } })
  const cellClass = `flow-operation-cell${cell.kind === 'merge' ? ' is-merge' : ''}${cell.rowSpan > 1 ? ' spans-rows' : ''}${drop.isOver ? ' is-drop-target' : ''}`
  return <article
    ref={drop.setNodeRef}
    className={cellClass}
    style={{ gridColumn: cell.column + 2, gridRow: `${cell.rowStart + 2} / span ${cell.rowSpan}` }}
    role="gridcell"
    aria-label={`Operation ${label}. ${uses.length ? `Uses ${uses.map(use => use.name).join(', ')}.` : 'Setup operation.'}`}
  >
    <div className="flow-operation-rail" aria-hidden="true"><span/>{cell.kind === 'merge' ? <Layers3 size={15}/> : <span/>}</div>
    {editable && <button ref={drag.setNodeRef} type="button" className="flow-operation-handle" aria-label={`Move ${action.text}`} {...drag.attributes} {...drag.listeners}><GripVertical size={14}/></button>}
    <div className="flow-operation-button" role="button" tabIndex={0} onClick={onSelect} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect() } }}>
      <span className="flow-operation-kicker">{cell.kind === 'merge' ? 'Merge' : cell.kind === 'setup' ? 'Setup' : 'Step'}</span>
      {editable ? <input aria-label={`Compact label for ${action.text}`} maxLength={120} value={label} onClick={event => event.stopPropagation()} onChange={event => onLabelChange(event.target.value)}/> : <strong>{label}</strong>}
      <ActionMeta action={action}/>
      {action.confidence < .65 && <Badge tone="warning"><WandSparkles size={12}/>Check suggestion</Badge>}
      {uses.length > 0 && <div className="flow-use-chips">{uses.map(use => <span key={use.binding_id} className="flow-use-chip" title={use.display}><span>{use.display}</span>{editable && onDisconnect && <button type="button" aria-label={`Disconnect ${use.display} from ${action.text}`} onClick={event => { event.stopPropagation(); onDisconnect(use.binding_id) }}><X size={11}/></button>}</span>)}</div>}
    </div>
    {editable && <div className="flow-action-drop-zones" aria-label={`Place ${action.text}`}>
      <DropZone id={`flow-before:${action.id}`} label="Before" type="flow-before" actionId={action.id}/>
      <DropZone id={`flow-merge:${action.id}`} label="Merge into" type="flow-merge" actionId={action.id}/>
      <DropZone id={`flow-after:${action.id}`} label="After" type="flow-after" actionId={action.id}/>
    </div>}
  </article>
}

function DropZone({ id, label, type, actionId }: { id: string; label: string; type: string; actionId: string }) {
  const drop = useDroppable({ id, data: { type, actionId } })
  return <span ref={drop.setNodeRef} className={`flow-drop-zone${drop.isOver ? ' is-over' : ''}`} aria-label={label}>{label}</span>
}

function IngredientRailRow({ row, ingredient, editable, rowNumber, onMove }: { row: FlowRow; ingredient?: BackendMethodIngredient; editable: boolean; rowNumber: number; onMove?: (direction: 'up' | 'down') => void }) {
  const sortable = useSortable({ id: row.id, disabled: !editable, data: { type: 'binding-row', bindingId: row.bindingId } })
  const style = { gridColumn: 1, gridRow: rowNumber, ...(editable ? { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition } : {}) }
  if (row.kind === 'setup') return <div className="flow-rail-row flow-rail-row--setup" style={style} role="rowheader"><span className="flow-rail-mark"><WandSparkles size={14}/></span><strong>{row.label}</strong><small>no material input</small></div>
  return <div ref={editable ? sortable.setNodeRef : undefined} style={style} className={`flow-rail-row${sortable.isDragging ? ' is-dragging' : ''}`} role="rowheader">
    {editable && <button type="button" className="flow-row-handle" aria-label={`Reorder ${ingredient?.name ?? row.ingredientLineageId}`} {...sortable.attributes} {...sortable.listeners}><GripVertical size={15}/></button>}
    <span className="flow-rail-mark" aria-hidden="true"/>
    <span className="flow-rail-quantity">{ingredient?.quantity_text} {ingredient?.unit}</span>
    <strong>{ingredient?.name ?? row.ingredientLineageId}</strong>
    {ingredient?.preparation && <small>{ingredient.preparation}</small>}
    {editable && onMove && <span className="flow-row-actions"><button type="button" aria-label={`Move ${ingredient?.name ?? row.ingredientLineageId} up`} onClick={() => onMove('up')}><ArrowUp size={13}/></button><button type="button" aria-label={`Move ${ingredient?.name ?? row.ingredientLineageId} down`} onClick={() => onMove('down')}><ArrowDown size={13}/></button></span>}
  </div>
}

function UnplacedTray({
  data,
  method,
  table,
  editable,
}: {
  data: BackendMethodView
  method: BackendMethodDocument
  table: BackendMethodTableDocument
  editable: boolean
}) {
  if (!editable) return null
  const used = new Set(method.ingredient_bindings.filter(binding => binding.role !== 'reference').map(binding => binding.ingredient_lineage_id))
  const unplaced = data.ingredients.filter(ingredient => !used.has(ingredient.lineage_id))
  const represented = new Set(table.labels.map(label => label.action_id))
  const missingActions = method.actions.filter(action => !represented.has(action.id))
  return <aside className="flow-unplaced-tray" aria-label="Unplaced ingredients and actions">
    <div className="flow-unplaced-heading"><div><span className="eyebrow">Draft tray</span><h3>Unplaced</h3></div><Badge tone={unplaced.length || missingActions.length ? 'warning' : 'green'}>{unplaced.length + missingActions.length}</Badge></div>
    {!unplaced.length && !missingActions.length ? <p className="muted">Everything is represented. Drop a used ingredient again to split its quantity.</p> : <>
      {unplaced.length > 0 && <div className="flow-tray-group"><small>Ingredients</small>{unplaced.map(ingredient => <DraggableTrayItem key={ingredient.lineage_id} id={`ingredient:${ingredient.lineage_id}`} label={ingredient.display} type="ingredient"/>)}</div>}
      {missingActions.length > 0 && <div className="flow-tray-group"><small>Operations</small>{missingActions.map(action => <DraggableTrayItem key={action.id} id={`flow-action:${action.id}`} label={action.text} type="flow-action"/>)}</div>}
    </>}
    {(data.table?.warnings ?? []).length > 0 && <div className="flow-tray-group flow-tray-warnings"><small>Parser warnings</small>{(data.table?.warnings ?? []).slice(0, 4).map(warning => <div className="flow-tray-warning" key={`${warning.code}-${warning.entity_id ?? ''}`}><WandSparkles size={13}/><span>{warning.message}</span></div>)}</div>}
    <p className="flow-tray-help"><Link2 size={13}/> Drag an ingredient onto a step to place a use.</p>
  </aside>
}

function DraggableTrayItem({ id, label, type }: { id: string; label: string; type: string }) {
  const drag = useDraggable({ id, data: { type, label } })
  return <button ref={drag.setNodeRef} style={{ transform: CSS.Translate.toString(drag.transform) }} className={`flow-tray-item${drag.isDragging ? ' is-dragging' : ''}`} type="button" {...drag.attributes} {...drag.listeners}><GripVertical size={14}/><span>{label}</span></button>
}

function FlowDetails({ action, label, data, method, table, onClose, editable, onLabelChange }: { action: BackendMethodAction; label: string; data: BackendMethodView; method: BackendMethodDocument; table: BackendMethodTableDocument; onClose: () => void; editable: boolean; onLabelChange: (value: string) => void }) {
  const annotationIds = new Set(action.source_annotation_ids)
  const sourceAnnotation = data.method.annotations.find(annotation => action.source_annotation_ids.includes(annotation.id))
  const sourceBlock = sourceAnnotation ? data.source_blocks.find(block => block.id === sourceAnnotation.block_id) : undefined
  const source = sourceBlock ? sourceBlock.text.slice(Math.max(0, sourceAnnotation?.start ?? 0), Math.min(sourceBlock.text.length, sourceAnnotation?.end ?? sourceBlock.text.length)) : undefined
  const bindings = method.ingredient_bindings.filter(binding => binding.action_id === action.id)
  const ingredientNames = bindings.map(binding => data.ingredients.find(ingredient => ingredient.lineage_id === binding.ingredient_lineage_id)?.name ?? binding.ingredient_lineage_id)
  const priorOutputs = method.edges.filter(edge => edge.to_action_id === action.id).map(edge => method.actions.find(item => item.id === edge.from_action_id)?.text ?? edge.from_action_id)
  return <aside className="flow-details" aria-label={`Details for ${label}`}>
    <div className="flow-details-heading"><div><span className="eyebrow">Operation details</span><h3>{label}</h3></div><button type="button" className="flow-details-close" aria-label="Close operation details" onClick={onClose}><X size={17}/></button></div>
    {editable ? <label>Compact table label<input value={label} maxLength={120} onChange={event => onLabelChange(event.target.value)}/></label> : <div className="flow-detail-label"><strong>{label}</strong><Badge tone={table.labels.find(item => item.action_id === action.id)?.accepted ? 'green' : 'warning'}>{table.labels.find(item => item.action_id === action.id)?.accepted ? 'Accepted' : 'Automatic draft'}</Badge></div>}
    <div className="flow-detail-section"><small>Full action</small><p>{action.text}</p></div>
    <div className="flow-detail-section"><small>Inputs and prior outputs</small><p>{[...ingredientNames, ...priorOutputs].join(', ') || 'Setup operation with no material input.'}</p></div>
    <ActionMeta action={action}/>
    {source && <div className="flow-detail-section"><small>Source clause</small><p>{source}</p></div>}
    <div className="flow-detail-section"><small>Review signal</small><p>{action.confidence < .65 ? 'This operation was parsed with low confidence. Edit or accept it before reviewing the table.' : 'This operation is available immediately; confirm the compact label against the source.'}</p></div>
    <div className="sr-only">{annotationIds.size} source annotations attached.</div>
  </aside>
}

export function RecipeFlowTable({ data, method, table, editable = false, onTableChange, onMethodChange, onSelectAction }: RecipeFlowTableProps) {
  const [selectedActionId, setSelectedActionId] = useState<string | null>(null)
  const layout = useMemo(() => createFlowTableLayout(method, table), [method, table])
  const actionMap = useMemo(() => new Map(method.actions.map(action => [action.id, action])), [method.actions])
  const ingredientMap = useMemo(() => new Map(data.ingredients.map(ingredient => [ingredient.lineage_id, ingredient])), [data.ingredients])
  const uses = useMemo(() => {
    const rendered = data.table?.rendered_ingredient_uses ?? []
    const local = method.ingredient_bindings.filter(binding => binding.role !== 'reference').flatMap(binding => {
      const ingredient = ingredientMap.get(binding.ingredient_lineage_id)
      if (!ingredient) return []
      const baseQuantity = ingredient.quantity == null ? undefined : Number(ingredient.quantity)
      const quantity = binding.portion_mode === 'fraction' && binding.portion_value != null && baseQuantity != null
        ? baseQuantity * Number(binding.portion_value)
        : baseQuantity
      const quantityText = quantity == null ? ingredient.quantity_text : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(quantity)
      const displayName = ingredient.preparation ? `${ingredient.name}, ${ingredient.preparation}` : ingredient.name
      const display = [quantityText, ingredient.unit, displayName].filter(Boolean).join(' ')
      return [[binding.id, { binding_id: binding.id, ingredient_lineage_id: binding.ingredient_lineage_id, target_action_id: binding.action_id, name: ingredient.name, quantity, quantity_text: quantityText, unit: ingredient.unit, portion_mode: binding.portion_mode, portion_value: binding.portion_value, portion_unit: binding.portion_unit, optional: ingredient.optional, preparation: ingredient.preparation, display } satisfies BackendMethodTableIngredientUse] as const]
    })
    return new Map([...local, ...rendered.map(use => [use.binding_id, use] as const)])
  }, [data.table?.rendered_ingredient_uses, ingredientMap, method.ingredient_bindings])
  const labelMap = useMemo(() => new Map(table.labels.map(label => [label.action_id, label])), [table.labels])
  const cells = useMemo(() => new Map(layout.cells.map(cell => [cell.actionId, cell])), [layout.cells])
  const selectedAction = selectedActionId ? actionMap.get(selectedActionId) : undefined
  const moveRow = (bindingId: string, direction: 'up' | 'down') => {
    if (!onTableChange) return
    const current = table.row_order.length ? [...table.row_order] : method.ingredient_bindings.filter(binding => binding.role !== 'reference').map(binding => binding.id)
    const index = current.indexOf(bindingId)
    const target = direction === 'up' ? index - 1 : index + 1
    if (index < 0 || target < 0 || target >= current.length) return
    const next = [...current]
    ;[next[index], next[target]] = [next[target], next[index]]
    onTableChange({ ...table, row_order: next })
  }
  const changeLabel = (actionId: string, value: string) => {
    if (!onTableChange) return
    const existing = table.labels.find(label => label.action_id === actionId)
    const nextLabel = { action_id: actionId, text: value.slice(0, 120), origin: 'user' as const, confidence: 1, accepted: true }
    onTableChange({ ...table, labels: [...table.labels.filter(label => label.action_id !== actionId), existing ? { ...existing, ...nextLabel } : nextLabel] })
  }
  const disconnectBinding = (bindingId: string) => {
    onMethodChange?.({ ...method, ingredient_bindings: method.ingredient_bindings.filter(binding => binding.id !== bindingId) })
    onTableChange?.({ ...table, row_order: table.row_order.filter(id => id !== bindingId) })
  }
  const operationUses = (cell: FlowCell) => cell.inputBindingIds.map(bindingId => uses.get(bindingId)).filter((use): use is BackendMethodTableIngredientUse => Boolean(use))
  return <section className={`recipe-flow-table${editable ? ' recipe-flow-table--editor' : ''}`} aria-label={editable ? 'Editable Flow table' : 'Recipe Flow table'}>
    <UnplacedTray data={data} method={method} table={table} editable={editable}/>
    {layout.warnings.length > 0 && <div className="flow-warning-stack" aria-label="Flow table warnings">{layout.warnings.slice(0, 4).map(warning => <NoticeLike key={`${warning.code}-${warning.entityId ?? ''}`} tone={warning.blocking ? 'warning' : 'info'}>{warning.message}</NoticeLike>)}</div>}
    <div className="flow-table-scroll" tabIndex={0} aria-label="Swipe through cooking operations">
      <div className="flow-table-grid" role="grid" aria-rowcount={layout.rows.length + 1} aria-colcount={layout.columns.length + 1} style={{ gridTemplateColumns: `minmax(218px, 260px) repeat(${Math.max(layout.columns.length, 1)}, minmax(180px, 1fr))`, gridTemplateRows: `auto repeat(${Math.max(layout.rows.length, 1)}, minmax(82px, auto))` }}>
        <div className="flow-table-corner" role="columnheader"><span className="eyebrow">Flow table</span><strong>Ingredients → operations</strong><small>Rows are scaled uses</small></div>
        {layout.columns.map(column => <div className="flow-table-column-heading" role="columnheader" key={column.actionId} style={{ gridColumn: column.index + 2, gridRow: 1 }}><span>{String(column.index + 1).padStart(2, '0')}</span><strong>{column.stageTitle}</strong><small>{column.label}</small></div>)}
        {layout.rows.map((row, rowIndex) => <IngredientRailRow key={row.id} row={row} rowNumber={rowIndex + 2} ingredient={row.ingredientLineageId ? ingredientMap.get(row.ingredientLineageId) : undefined} editable={editable} onMove={row.bindingId ? direction => moveRow(row.bindingId!, direction) : undefined}/>)}
        {layout.cells.map(cell => {
          const action = actionMap.get(cell.actionId)
          if (!action) return null
          const label = labelMap.get(action.id)?.text ?? action.text
          return <OperationCell key={cell.actionId} action={action} cell={cell} label={label} uses={operationUses(cell)} editable={editable} onLabelChange={value => changeLabel(action.id, value)} onDisconnect={disconnectBinding} onSelect={() => { setSelectedActionId(action.id); onSelectAction?.(action.id) }}/>
        })}
        {layout.connectors.map(connector => <span key={connector.edgeId} className={`flow-connector flow-connector--${connector.kind}`} aria-hidden="true" style={{ gridColumn: connector.column + 2, gridRow: `${Math.min(connector.fromRow, connector.toRow) + 2} / span ${Math.max(1, Math.abs(connector.toRow - connector.fromRow) + 1)}` }}/>) }
      </div>
      {layout.columns.length > 4 && <div className="flow-table-overflow-cue" aria-hidden="true">Swipe through steps <ChevronRight size={15}/></div>}
    </div>
    <div className="flow-linearisation sr-only" aria-label="Linear recipe flow">
      {layout.cells.map((cell, index) => { const action = actionMap.get(cell.actionId); return action ? <p key={cell.actionId}>Step {index + 1}, {labelMap.get(action.id)?.text ?? action.text}, combines {operationUses(cell).map(use => use.name).join(', ') || 'setup only'}.</p> : null })}
    </div>
    {selectedAction && <FlowDetails action={selectedAction} label={labelMap.get(selectedAction.id)?.text ?? selectedAction.text} data={data} method={method} table={table} onClose={() => setSelectedActionId(null)} editable={editable} onLabelChange={value => changeLabel(selectedAction.id, value)}/>}
  </section>
}

function NoticeLike({ tone, children }: { tone: 'warning' | 'info'; children: string }) {
  return <div className={`flow-warning flow-warning--${tone}`}><WandSparkles size={15}/><span>{children}</span></div>
}
