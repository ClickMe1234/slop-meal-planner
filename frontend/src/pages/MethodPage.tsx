import {
  closestCenter,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpenText,
  Check,
  ChefHat,
  CircleHelp,
  Clock3,
  ExternalLink,
  Flame,
  GripVertical,
  Layers3,
  Link2,
  MousePointer2,
  PencilLine,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Split,
  Tag,
  Thermometer,
  Trash2,
  Utensils,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  ApiError,
  isDemoMode,
  type BackendMethodAction,
  type BackendMethodAnnotation,
  type BackendMethodBinding,
  type BackendMethodDocument,
  type BackendMethodIngredient,
  type BackendMethodSourceBlock,
  type BackendMethodStage,
  type BackendMethodTableDocument,
  type BackendMethodView,
  type BackendRecipeDetail,
  type MethodSemanticKind,
  type MethodViewPreference,
} from '../api/client'
import { MealTypePicker, type RecipeMealType } from '../components/MealTypePicker'
import { Badge, Button, Card, Loading, Notice, PageHeader, Segmented } from '../components/ui'
import { safeExternalUrl } from '../lib/safeUrls'
import { emptyTableDocument, RecipeFlowTable } from '../components/RecipeFlowTable'

const TUTORIAL_VERSION = 2
const semanticTools: Array<{ kind: MethodSemanticKind; label: string; icon: typeof Tag }> = [
  { kind: 'ingredient', label: 'Ingredient', icon: Tag },
  { kind: 'action', label: 'Action', icon: Sparkles },
  { kind: 'time', label: 'Time', icon: Clock3 },
  { kind: 'temperature', label: 'Temperature', icon: Thermometer },
  { kind: 'equipment', label: 'Equipment', icon: Utensils },
  { kind: 'cue', label: 'Doneness cue', icon: Check },
]

const localId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`
const REVIEW_CONFIDENCE_THRESHOLD = .65

function isUnreviewedClause(annotation: BackendMethodAnnotation) {
  return annotation.kind === 'action' && Number(annotation.confidence) < REVIEW_CONFIDENCE_THRESHOLD && !annotation.accepted
}

function unreviewedClauses(sourceBlocks: BackendMethodSourceBlock[], annotations: BackendMethodAnnotation[]) {
  const blocks = new Map(sourceBlocks.map(block => [block.id, block]))
  return annotations
    .filter(isUnreviewedClause)
    .map(annotation => {
      const block = blocks.get(annotation.block_id)
      const text = block?.text.slice(annotation.start, annotation.end).trim() ?? ''
      return { annotation, text }
    })
    .filter(item => item.text)
}

function annotatedSource(block: BackendMethodSourceBlock, annotations: BackendMethodAnnotation[]) {
  const ordered = annotations
    .filter(item => item.block_id === block.id && item.start >= 0 && item.end <= block.text.length && item.end > item.start)
    .sort((left, right) => left.start - right.start || right.end - left.end)
  const parts: Array<{ text: string; annotation?: BackendMethodAnnotation }> = []
  let cursor = 0
  for (const annotation of ordered) {
    if (annotation.start < cursor) continue
    if (annotation.start > cursor) parts.push({ text: block.text.slice(cursor, annotation.start) })
    parts.push({ text: block.text.slice(annotation.start, annotation.end), annotation })
    cursor = annotation.end
  }
  if (cursor < block.text.length) parts.push({ text: block.text.slice(cursor) })
  return parts.map((part, index) => {
    if (!part.annotation) return <span key={`text-${index}`}>{part.text}</span>
    const unreviewed = isUnreviewedClause(part.annotation)
    return <mark
      key={`${part.annotation.id}-${index}`}
      id={unreviewed ? `unreviewed-clause-${part.annotation.id}` : undefined}
      data-unreviewed-clause={unreviewed ? 'true' : undefined}
      tabIndex={unreviewed ? -1 : undefined}
      className={`semantic-mark semantic-mark--${part.annotation.kind}${part.annotation.accepted ? ' accepted' : ''}${unreviewed ? ' semantic-mark--unreviewed' : ''}`}
      title={unreviewed ? 'Unaccounted source clause' : `${part.annotation.kind}${part.annotation.confidence < REVIEW_CONFIDENCE_THRESHOLD ? ' · check this suggestion' : ''}`}
      aria-label={unreviewed ? `Unaccounted source clause: ${part.text}` : undefined}
    >{part.text}</mark>
  })
}

function manualDocument(text: string): { blocks: BackendMethodSourceBlock[]; method: BackendMethodDocument } {
  const block: BackendMethodSourceBlock = { id: 'block-1', position: 0, text: text.trim() }
  const clauses = [...text.matchAll(/[^.!?;\n]+(?:[.!?;]+|$)/g)].filter(match => match[0].trim())
  const annotations: BackendMethodAnnotation[] = clauses.map((match, index) => ({
    id: `annotation-${index + 1}`,
    block_id: block.id,
    start: match.index ?? 0,
    end: (match.index ?? 0) + match[0].length,
    kind: 'action',
    origin: 'user',
    confidence: 1,
    accepted: true,
  }))
  const actions: BackendMethodAction[] = clauses.map((match, index) => ({
    id: `action-${index + 1}`,
    stage_id: 'stage-1',
    position: index,
    text: match[0].trim().replace(/[.;]+$/, ''),
    source_annotation_ids: [annotations[index].id],
    equipment: [],
    confidence: 1,
  }))
  return {
    blocks: [block],
    method: {
      schema_version: 1,
      annotations,
      omissions: [],
      stages: [{ id: 'stage-1', title: 'Method', position: 0 }],
      actions,
      ingredient_bindings: [],
      edges: actions.slice(1).map((action, index) => ({
        id: `edge-${index + 1}`,
        from_action_id: actions[index].id,
        to_action_id: action.id,
        kind: 'sequence',
        confidence: 1,
      })),
    },
  }
}

function draftTableDocument(method: BackendMethodDocument): BackendMethodTableDocument {
  const inputBindings = method.ingredient_bindings.filter(binding => binding.role !== 'reference')
  const outgoing = new Set(method.edges.map(edge => edge.from_action_id))
  return {
    ...emptyTableDocument(),
    labels: method.actions.map(action => ({ action_id: action.id, text: action.text.slice(0, 120), origin: 'automatic' as const, confidence: action.confidence, accepted: action.confidence >= REVIEW_CONFIDENCE_THRESHOLD })),
    row_order: inputBindings.map(binding => binding.id),
    setup_action_ids: method.actions.filter(action => !inputBindings.some(binding => binding.action_id === action.id)).map(action => action.id),
    terminal_action_ids: method.actions.filter(action => !outgoing.has(action.id)).map(action => action.id),
  }
}

function wouldCreateCycle(document: BackendMethodDocument, fromActionId: string, toActionId: string) {
  const outgoing = new Map<string, string[]>(document.actions.map(action => [action.id, []]))
  document.edges.forEach(edge => outgoing.get(edge.from_action_id)?.push(edge.to_action_id))
  const pending = [toActionId]
  const visited = new Set<string>()
  while (pending.length) {
    const current = pending.pop()!
    if (current === fromActionId) return true
    if (visited.has(current)) continue
    visited.add(current)
    pending.push(...(outgoing.get(current) ?? []))
  }
  return false
}

export function MethodPreviewPage() {
  return <MethodPage preview />
}

export function MethodPage({ preview = false }: { preview?: boolean }) {
  const { recipeId } = useParams()
  const [searchParams] = useSearchParams()
  const batchId = searchParams.get('batch') ?? undefined
  const sourceUrl = searchParams.get('url') ?? ''
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session'], queryFn: api.me, enabled: !isDemoMode, retry: false })
  const recipe = useQuery({ queryKey: ['recipe', recipeId], queryFn: () => api.getRecipe(recipeId!), enabled: Boolean(recipeId) && !preview && !isDemoMode })
  const [servings, setServings] = useState<number | undefined>()
  const [view, setView] = useState<MethodViewPreference>('summary')
  const methodQuery = useQuery({
    queryKey: preview ? ['method-preview', sourceUrl] : ['recipe-method', recipeId, batchId, servings],
    queryFn: () => preview ? api.methodPreview(sourceUrl) : api.getRecipeMethod(recipeId!, { batchId, servings }),
    enabled: !isDemoMode && (preview ? Boolean(sourceUrl) : Boolean(recipeId)),
    retry: false,
  })
  const [data, setData] = useState<BackendMethodView | null>(null)
  const [method, setMethod] = useState<BackendMethodDocument | null>(null)
  const [table, setTable] = useState<BackendMethodTableDocument | null>(null)
  const [sourceBlocks, setSourceBlocks] = useState<BackendMethodSourceBlock[]>([])
  const [notes, setNotes] = useState('')
  const [editing, setEditing] = useState(false)
  const [editorPane, setEditorPane] = useState<'source' | 'flow'>('flow')
  const [savePending, setSavePending] = useState<'draft' | 'review' | null>(null)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [manualText, setManualText] = useState('')
  const [mealTypes, setMealTypes] = useState<RecipeMealType[]>([])
  const [selectedIngredients, setSelectedIngredients] = useState<Set<string>>(new Set())
  const [selectedActions, setSelectedActions] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<{ blockId: string; start: number; end: number; text: string } | null>(null)
  const [annotationIngredient, setAnnotationIngredient] = useState('')
  const [activeDrag, setActiveDrag] = useState<{ id: string; type: 'ingredient' | 'action' | 'flow-action' | 'binding-row'; label: string } | null>(null)
  const [pendingPlacement, setPendingPlacement] = useState<{ lineageId: string; actionId: string } | null>(null)
  const [placementAmount, setPlacementAmount] = useState('0.5')
  const [breakingAction, setBreakingAction] = useState<string | null>(null)
  const [breakingStrength, setBreakingStrength] = useState(0)
  const [justGrouped, setJustGrouped] = useState<string | null>(null)
  const [tutorialStep, setTutorialStep] = useState<number | null>(null)
  const [conflictLatest, setConflictLatest] = useState<BackendMethodView | null>(null)
  const [refreshCandidate, setRefreshCandidate] = useState<BackendMethodView | null>(null)

  useEffect(() => {
    if (session.data?.method_view_preference) setView(session.data.method_view_preference)
    if ((session.data?.method_tutorial_version_seen ?? TUTORIAL_VERSION) < TUTORIAL_VERSION) setTutorialStep(0)
  }, [session.data?.method_view_preference, session.data?.method_tutorial_version_seen])
  useEffect(() => {
    if (!methodQuery.data || dirty) return
    setData(methodQuery.data)
    setMethod(structuredClone(methodQuery.data.method))
    setTable(structuredClone(methodQuery.data.table?.document ?? draftTableDocument(methodQuery.data.method)))
    setSourceBlocks(structuredClone(methodQuery.data.source_blocks))
    setNotes(methodQuery.data.household_notes ?? '')
    setAnnotationIngredient(methodQuery.data.ingredients[0]?.lineage_id ?? '')
  }, [methodQuery.data, dirty])

  const toggleView = async (next: MethodViewPreference) => {
    setView(next)
    if (!isDemoMode) {
      await api.updateMe({ method_view_preference: next })
      await queryClient.invalidateQueries({ queryKey: ['session'] })
    }
  }
  const dismissTutorial = async () => {
    setTutorialStep(null)
    if (!isDemoMode) {
      await api.updateMe({ method_tutorial_version_seen: TUTORIAL_VERSION })
      await queryClient.invalidateQueries({ queryKey: ['session'] })
    }
  }

  const extract = useMutation({
    mutationFn: () => api.extractRecipeMethod(recipeId!, recipe.data?.version),
    onSuccess: result => {
      setData(result); setMethod(structuredClone(result.method)); setSourceBlocks(structuredClone(result.source_blocks)); setMessage('Method draft created.'); setError('')
      setTable(structuredClone(result.table?.document ?? draftTableDocument(result.method)))
      void queryClient.invalidateQueries({ queryKey: ['recipes'] })
    },
    onError: reason => setError(reason instanceof Error ? reason.message : 'The method could not be extracted.'),
  })

  const savePreview = useMutation({
    mutationFn: () => api.saveMethodPreview(data!.preview_token!, mealTypes),
    onSuccess: saved => {
      void queryClient.invalidateQueries({ queryKey: ['recipes'] })
      navigate(`/recipes/${saved.id}/method`, { replace: true })
    },
    onError: reason => setError(reason instanceof Error ? reason.message : 'The recipe could not be saved.'),
  })

  const refreshPreview = useMutation({
    mutationFn: () => api.previewMethodRefresh(recipeId!),
    onSuccess: result => { setRefreshCandidate(result); setError('') },
    onError: reason => setError(reason instanceof Error ? reason.message : 'The source method could not be refreshed.'),
  })
  const applyRefresh = useMutation({
    mutationFn: () => api.applyMethodRefresh(recipeId!, data!.recipe_version!, refreshCandidate!.preview_token!),
    onSuccess: result => {
      setData(result); setMethod(structuredClone(result.method)); setTable(structuredClone(result.table?.document ?? draftTableDocument(result.method))); setSourceBlocks(structuredClone(result.source_blocks)); setRefreshCandidate(null); setDirty(false)
      setMessage('The latest source method is ready for review.')
      void queryClient.invalidateQueries({ queryKey: ['recipes'] })
    },
    onError: reason => setError(reason instanceof Error ? reason.message : 'The refreshed method could not be applied.'),
  })

  const saveMethod = async (markReviewed = false) => {
    if (!recipeId || preview || !method || !data?.recipe_version || savePending || (markReviewed && data.method_status !== 'needs_review')) return
    setSavePending(markReviewed ? 'review' : 'draft')
    setError(''); setMessage('')
    try {
      const result = await api.saveRecipeMethod(recipeId, {
        expected_version: data.recipe_version,
        method,
        household_notes: notes || undefined,
        mark_reviewed: markReviewed,
        source_kind: data.source_kind as 'custom' | 'publisher' | 'manual_paste',
        source_blocks: data.source_kind === 'publisher' ? undefined : sourceBlocks,
      })
      setData(result); setMethod(structuredClone(result.method)); setTable(structuredClone(result.table?.document ?? draftTableDocument(result.method))); setSourceBlocks(structuredClone(result.source_blocks)); setDirty(false); setEditing(false)
      setMessage(markReviewed ? 'Method reviewed and saved.' : 'Method draft saved.')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['recipes'] }),
        queryClient.invalidateQueries({ queryKey: ['recipe', recipeId] }),
        queryClient.invalidateQueries({ queryKey: ['recipe-method', recipeId] }),
      ])
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        try { setConflictLatest(await api.getRecipeMethod(recipeId, { batchId })) } catch { setError(reason.message) }
      } else setError(reason instanceof Error ? reason.message : 'The method could not be saved.')
    } finally {
      setSavePending(null)
    }
  }

  const saveTable = async (markReviewed = false) => {
    if (!recipeId || preview || !method || !table || !data?.recipe_version || savePending) return
    setSavePending(markReviewed ? 'review' : 'draft')
    setError(''); setMessage('')
    try {
      const result = await api.saveRecipeMethodTable(recipeId, {
        expected_version: data.recipe_version,
        method,
        table,
        mark_reviewed: markReviewed,
      })
      setData(result)
      setMethod(structuredClone(result.method))
      setTable(structuredClone(result.table?.document ?? table))
      setSourceBlocks(structuredClone(result.source_blocks))
      setDirty(false)
      setEditing(false)
      setMessage(markReviewed ? 'Flow table reviewed and saved.' : 'Flow table draft saved.')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['recipes'] }),
        queryClient.invalidateQueries({ queryKey: ['recipe', recipeId] }),
        queryClient.invalidateQueries({ queryKey: ['recipe-method', recipeId] }),
      ])
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        try { setConflictLatest(await api.getRecipeMethod(recipeId, { batchId })) } catch { setError(reason.message) }
      } else setError(reason instanceof Error ? reason.message : 'The Flow table could not be saved.')
    } finally {
      setSavePending(null)
    }
  }

  const createManual = async () => {
    if (!recipeId || !manualText.trim() || !recipe.data) return
    const generated = manualDocument(manualText)
    setData({
      recipe_id: recipeId,
      recipe_version: recipe.data.version,
      title: recipe.data.title,
      publisher: recipe.data.publisher,
      source_url: recipe.data.source_url,
      method_status: 'needs_review',
      source_kind: recipe.data.source_type === 'custom' ? 'custom' : 'manual_paste',
      source_blocks: generated.blocks,
      method: generated.method,
      coverage: { total_clauses: generated.method.actions.length, represented: generated.method.actions.length, omitted: 0, unreviewed: 0 },
      ingredients: recipe.data.ingredients.map(item => ({ id: item.id, lineage_id: item.lineage_id ?? item.id, name: item.food_phrase ?? item.original_text, quantity: item.quantity, quantity_text: item.quantity == null ? undefined : String(item.quantity), unit: item.unit, display: [item.quantity, item.unit, item.food_phrase ?? item.original_text].filter(Boolean).join(' '), optional: item.optional, preparation: item.preparation })),
      rendered_blocks: generated.blocks.map(block => ({ ...block, segments: [{ kind: 'text', text: block.text }] })),
      base_servings: recipe.data.yield_servings,
      requested_servings: recipe.data.yield_servings,
      scaling_available: Boolean(recipe.data.yield_servings),
    })
    setMethod(generated.method); setSourceBlocks(generated.blocks); setDirty(true); setEditing(true); setError('')
    setTable(draftTableDocument(generated.method))
  }

  const updateDocument = (updater: (current: BackendMethodDocument) => BackendMethodDocument) => {
    setMethod(current => current ? updater(current) : current)
    setDirty(true)
  }
  const acceptSuggestions = () => updateDocument(current => ({
    ...current,
    annotations: current.annotations.map(item => ({ ...item, accepted: true })),
    ingredient_bindings: current.ingredient_bindings.map(item => ({ ...item, accepted: true })),
  }))

  const sourceRefs = useRef<Record<string, HTMLParagraphElement | null>>({})
  const captureSelection = (block: BackendMethodSourceBlock) => {
    const element = sourceRefs.current[block.id]
    const selected = window.getSelection()
    if (!element || !selected || selected.rangeCount === 0 || selected.isCollapsed) { setSelection(null); return }
    const range = selected.getRangeAt(0)
    if (!element.contains(range.commonAncestorContainer)) { setSelection(null); return }
    const prefix = range.cloneRange(); prefix.selectNodeContents(element); prefix.setEnd(range.startContainer, range.startOffset)
    const start = prefix.toString().length
    const text = range.toString()
    if (!text.trim()) { setSelection(null); return }
    setSelection({ blockId: block.id, start, end: start + text.length, text })
  }
  const tagSelection = (kind: MethodSemanticKind) => {
    if (!selection || !method) return
    const annotation: BackendMethodAnnotation = {
      id: localId('annotation'), block_id: selection.blockId, start: selection.start, end: selection.end,
      kind, origin: 'user', confidence: 1, accepted: true,
      ingredient_lineage_id: kind === 'ingredient' ? annotationIngredient : undefined,
    }
    updateDocument(current => {
      const next = { ...current, annotations: [...current.annotations, annotation] }
      if (kind === 'action') {
        const stage = current.stages[0] ?? { id: localId('stage'), title: 'Method', position: 0 }
        if (!current.stages.length) next.stages = [stage]
        next.actions = [...current.actions, { id: localId('action'), stage_id: stage.id, position: current.actions.length, text: selection.text.trim(), source_annotation_ids: [annotation.id], equipment: [], confidence: 1 }]
      }
      return next
    })
    window.getSelection()?.removeAllRanges(); setSelection(null)
  }
  const removeAnnotation = (id: string) => updateDocument(current => ({
    ...current,
    annotations: current.annotations.filter(item => item.id !== id),
    ingredient_bindings: current.ingredient_bindings.filter(item => item.annotation_id !== id),
    actions: current.actions.map(item => ({ ...item, source_annotation_ids: item.source_annotation_ids.filter(annotationId => annotationId !== id) })),
  }))

  const commitIngredientPlacement = (lineageId: string, actionId: string, portionMode: BackendMethodBinding['portion_mode'] = 'unspecified', portionValue?: number) => {
    if (method?.ingredient_bindings.some(item => item.action_id === actionId && item.ingredient_lineage_id === lineageId && item.portion_mode === portionMode && item.portion_value === portionValue)) return
    const bindingId = localId('binding')
    updateDocument(current => current.ingredient_bindings.some(item => item.action_id === actionId && item.ingredient_lineage_id === lineageId && item.portion_mode === portionMode && item.portion_value === portionValue) ? current : ({
      ...current,
      ingredient_bindings: [...current.ingredient_bindings, { id: bindingId, action_id: actionId, ingredient_lineage_id: lineageId, portion_mode: portionMode, portion_value: portionValue, confidence: 1, accepted: true }],
    }))
    setTable(current => current ? { ...current, row_order: current.row_order.includes(bindingId) ? current.row_order : [...current.row_order, bindingId] } : current)
    setJustGrouped(actionId); window.setTimeout(() => setJustGrouped(value => value === actionId ? null : value), 520)
  }
  const attachIngredient = (lineageId: string, actionId: string) => {
    if (method?.ingredient_bindings.some(item => item.role !== 'reference' && item.ingredient_lineage_id === lineageId)) {
      setPendingPlacement({ lineageId, actionId })
      return
    }
    commitIngredientPlacement(lineageId, actionId)
  }
  const chooseIngredientPlacement = (portionMode: BackendMethodBinding['portion_mode']) => {
    if (!pendingPlacement) return
    const amount = Number(placementAmount)
    if ((portionMode === 'fraction' || portionMode === 'absolute') && (!Number.isFinite(amount) || amount <= 0)) return
    commitIngredientPlacement(pendingPlacement.lineageId, pendingPlacement.actionId, portionMode, portionMode === 'fraction' || portionMode === 'absolute' ? amount : undefined)
    setPendingPlacement(null)
  }
  const groupSelection = () => {
    if (!method) return
    const actionId = [...selectedActions][0]
    if (actionId && selectedIngredients.size) {
      selectedIngredients.forEach(lineageId => attachIngredient(lineageId, actionId))
      setSelectedIngredients(new Set()); setSelectedActions(new Set()); return
    }
    if (selectedActions.size > 1) {
      const stage: BackendMethodStage = { id: localId('stage'), title: `Stage ${method.stages.length + 1}`, position: method.stages.length }
      updateDocument(current => ({ ...current, stages: [...current.stages, stage], actions: current.actions.map(action => selectedActions.has(action.id) ? { ...action, stage_id: stage.id } : action) }))
      setSelectedActions(new Set())
    }
  }
  const ungroupActions = () => {
    if (!method?.stages.length || !selectedActions.size) return
    const target = method.stages[0].id
    updateDocument(current => ({ ...current, actions: current.actions.map(action => selectedActions.has(action.id) ? { ...action, stage_id: target } : action) }))
    setSelectedActions(new Set())
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  const handleDragStart = (event: DragStartEvent) => {
    const type = event.active.data.current?.type as 'ingredient' | 'action' | 'flow-action' | 'binding-row'
    setActiveDrag({ id: String(event.active.id), type, label: String(event.active.data.current?.label ?? '') })
  }
  const handleDragMove = (event: DragMoveEvent) => {
    const distance = Math.abs(event.delta.x)
    if (event.active.data.current?.type === 'action' && distance > 65) {
      setBreakingAction(String(event.active.id))
      setBreakingStrength(Math.min(1, (distance - 65) / 55))
    } else {
      setBreakingAction(null)
      setBreakingStrength(0)
    }
  }
  const handleDragEnd = (event: DragEndEvent) => {
    const activeType = event.active.data.current?.type
    const activeId = String(event.active.id)
    const overId = event.over ? String(event.over.id) : ''
    if (activeType === 'ingredient' && ['action', 'flow-action'].includes(String(event.over?.data.current?.type))) attachIngredient(activeId.replace('ingredient:', ''), overId.replace(/^(?:action|flow-action):/, ''))
    if (activeType === 'binding-row' && event.over?.data.current?.type === 'binding-row' && table) {
      const current = table.row_order.length ? [...table.row_order] : method?.ingredient_bindings.filter(binding => binding.role !== 'reference').map(binding => binding.id) ?? []
      const fromId = activeId.replace('binding:', '')
      const toId = overId.replace('binding:', '')
      const fromIndex = current.indexOf(fromId)
      const toIndex = current.indexOf(toId)
      if (fromIndex >= 0 && toIndex >= 0 && fromIndex !== toIndex) {
        const next = [...current]
        ;[next[fromIndex], next[toIndex]] = [next[toIndex], next[fromIndex]]
        setTable({ ...table, row_order: next }); setDirty(true)
      }
    }
    if (activeType === 'flow-action' && method && event.over) {
      const actionId = activeId.replace('flow-action:', '')
      const targetType = String(event.over.data.current?.type ?? '')
      const targetId = String(event.over.data.current?.actionId ?? '').replace(/^flow-action:/, '')
      if (targetId && targetId !== actionId && ['flow-before', 'flow-after'].includes(targetType)) {
        updateDocument(current => {
          const ordered = [...current.actions].sort((left, right) => left.position - right.position)
          const fromIndex = ordered.findIndex(action => action.id === actionId)
          const targetIndex = ordered.findIndex(action => action.id === targetId)
          if (fromIndex < 0 || targetIndex < 0) return current
          const [moved] = ordered.splice(fromIndex, 1)
          ordered.splice(targetType === 'flow-before' ? ordered.findIndex(action => action.id === targetId) : ordered.findIndex(action => action.id === targetId) + 1, 0, moved)
          return { ...current, actions: ordered.map((action, index) => ({ ...action, position: index })) }
        })
      }
      if (targetId && targetId !== actionId && targetType === 'flow-merge' && !method.edges.some(edge => edge.from_action_id === actionId && edge.to_action_id === targetId)) {
        if (wouldCreateCycle(method, actionId, targetId)) {
          setError('That merge would create a cycle. Choose an operation later in the flow.')
          setActiveDrag(null); setBreakingAction(null); setBreakingStrength(0)
          return
        }
        updateDocument(current => ({ ...current, edges: [...current.edges, { id: localId('edge'), from_action_id: actionId, to_action_id: targetId, kind: 'merge', confidence: 1, accepted: true }] }))
      }
    }
    if (activeType === 'action' && method) {
      const actionId = activeId.replace('action:', '')
      if (Math.abs(event.delta.x) > 120 && breakingAction) {
        const firstStage = method.stages[0]?.id
        if (firstStage) updateDocument(current => ({ ...current, actions: current.actions.map(action => action.id === actionId ? { ...action, stage_id: firstStage } : action) }))
      } else if (event.over?.data.current?.type === 'action') {
        const overActionId = overId.replace('action:', '')
        updateDocument(current => {
          const oldIndex = current.actions.findIndex(item => item.id === actionId)
          const newIndex = current.actions.findIndex(item => item.id === overActionId)
          if (oldIndex < 0 || newIndex < 0) return current
          const targetStage = current.actions[newIndex].stage_id
          const moved = current.actions.map(item => item.id === actionId ? { ...item, stage_id: targetStage } : item)
          return { ...current, actions: arrayMove(moved, oldIndex, newIndex).map((item, index) => ({ ...item, position: index })) }
        })
      } else if (event.over?.data.current?.type === 'stage') {
        const stageId = overId.replace('stage:', '')
        updateDocument(current => ({ ...current, actions: current.actions.map(action => action.id === actionId ? { ...action, stage_id: stageId } : action) }))
      }
    }
    setActiveDrag(null); setBreakingAction(null); setBreakingStrength(0)
  }

  const unavailable = methodQuery.error instanceof ApiError && ['METHOD_NOT_AVAILABLE', 'METHOD_NOT_FOUND'].includes(methodQuery.error.code ?? '')
  if (isDemoMode) return <div className="page page--wide"><Notice tone="info" title="Method demo">Method editing is available when connected to the private household API.</Notice></div>
  if (methodQuery.isLoading || session.isLoading) return <div className="page page--wide"><Loading label="Preparing the cooking method…"/></div>
  if (!data || !method) {
    return <div className="page page--narrow">
      <PageHeader eyebrow="Cooking method" title={recipe.data?.title ?? 'Create a method'} description="Fetch the source on demand, or write the method yourself."/>
      {error && <Notice tone="warning" title="Method unavailable">{error}</Notice>}
      {methodQuery.error && !unavailable && <Notice tone="warning" title="Method unavailable">{methodQuery.error instanceof Error ? methodQuery.error.message : 'The method could not be loaded.'}</Notice>}
      <Card className="method-empty-state">
        {recipe.data?.source_url && <Button disabled={extract.isPending} onClick={() => extract.mutate()}><Sparkles size={17}/>{extract.isPending ? 'Reading source…' : 'Create draft from source'}</Button>}
        <div className="method-empty-divider"><span>or</span></div>
        <label>Write or paste the cooking method<textarea rows={10} value={manualText} onChange={event => setManualText(event.target.value)} placeholder="Fry the onions until soft. Add the tomatoes…"/></label>
        <Button variant="secondary" disabled={!manualText.trim()} onClick={createManual}><PencilLine size={17}/>Build from this text</Button>
        {safeExternalUrl(recipe.data?.source_url) && <a className="source-link" href={safeExternalUrl(recipe.data?.source_url) ?? undefined} target="_blank" rel="noreferrer">Open original recipe <ExternalLink size={15}/></a>}
      </Card>
    </div>
  }

  const stages = [...method.stages].sort((a, b) => a.position - b.position)
  const unreviewed = Number(data.coverage.unreviewed ?? 0)
  const lowConfidence = method.annotations.filter(item => item.confidence < .65 && !item.accepted).length + method.ingredient_bindings.filter(item => item.confidence < .65 && !item.accepted).length
  const unresolvedClauses = unreviewedClauses(sourceBlocks, method.annotations)
  const reviewBlocked = data.source_kind === 'table_only' || unreviewed > 0 || lowConfidence > 0
  return <div className="page page--wide method-page">
    <PageHeader
      eyebrow={data.batch_context ? `Batch method · ${data.batch_context.servings} servings` : preview ? 'Method preview' : 'Cooking method'}
      title={data.title}
      description={data.publisher ? `From ${data.publisher}. Source wording is kept private and attributed.` : 'Your household cooking method.'}
      actions={<>
        <Link className="button button--ghost" to={batchId ? '/week' : '/recipes'}><ArrowLeft size={17}/>Back</Link>
        {safeExternalUrl(data.source_url) && <a className="button button--secondary" href={safeExternalUrl(data.source_url) ?? undefined} target="_blank" rel="noreferrer">Source <ExternalLink size={16}/></a>}
        {!preview && data.source_kind === 'publisher' && <Button variant="secondary" disabled={refreshPreview.isPending} onClick={() => refreshPreview.mutate()}><RefreshCw className={refreshPreview.isPending ? 'spin' : ''} size={16}/>{refreshPreview.isPending ? 'Checking…' : 'Check source'}</Button>}
        {!preview && data.method_status === 'needs_review' && <Button type="button" disabled={reviewBlocked || savePending !== null || Boolean(conflictLatest)} title={reviewBlocked ? 'Resolve the review blockers before marking this method as reviewed.' : undefined} onClick={() => void saveMethod(true)} aria-label="Mark as reviewed"><Check size={16}/>{savePending === 'review' ? 'Saving…' : 'Mark as reviewed'}</Button>}
        {!preview && <Button variant="secondary" onClick={() => setEditing(value => !value)}><PencilLine size={16}/>{editing ? 'Close editor' : data.source_kind === 'table_only' ? 'Start flow table' : 'Edit method'}</Button>}
      </>}
    />
    {error && <Notice tone="warning" title="Method update failed">{error}</Notice>}
    {message && <Notice tone="success" title="Saved">{message}</Notice>}
    <div className="method-status" aria-live="polite"><Badge tone={data.method_status === 'reviewed' ? 'green' : 'warning'}>{data.method_status === 'reviewed' ? 'Reviewed' : 'Needs review'}</Badge><Badge tone={data.table?.status === 'reviewed' ? 'green' : 'warning'}>{data.table?.status === 'reviewed' ? 'Flow table reviewed' : 'Flow table needs review'}</Badge></div>
    {data.method_status === 'needs_review' && <Notice tone="warning" title="Automatically generated draft">Use it now, or review {unreviewed ? `${unreviewed} unaccounted clause${unreviewed === 1 ? '' : 's'}` : 'the highlighted suggestions'} before marking it reviewed.</Notice>}
    {data.batch_context && <Card className="method-batch-banner"><Flame/><div><strong>Cook the whole batch: {data.batch_context.servings} servings</strong><span>{data.batch_context.occurrences.map(item => `${item.date} ${item.meal_type}`).join(' · ')}</span></div></Card>}
    <div className="method-toolbar">
      <Segmented value={view} onChange={toggleView} label="Method view" options={[{ value: 'summary', label: 'Summary' }, { value: 'table', label: 'Flow table' }, { value: 'written', label: 'Written' }]}/>
      {!data.batch_context && data.scaling_available && <label className="method-serving-control">Servings<input type="number" min=".25" step=".25" value={servings ?? data.requested_servings ?? ''} onChange={event => setServings(Number(event.target.value) || undefined)}/></label>}
      <button className="method-help-button" type="button" onClick={() => setTutorialStep(0)}><CircleHelp size={17}/>How to edit</button>
    </div>

    {preview && <Card className="method-preview-save"><div><span className="eyebrow">Keep this recipe</span><strong>Save ingredients, written method and summary together</strong></div><MealTypePicker value={mealTypes} onChange={setMealTypes}/><Button disabled={!mealTypes.length || savePreview.isPending} onClick={() => savePreview.mutate()}><Save size={16}/>{savePreview.isPending ? 'Saving…' : 'Save recipe'}</Button></Card>}

    {editing ? <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={handleDragStart} onDragMove={handleDragMove} onDragCancel={() => { setActiveDrag(null); setBreakingAction(null); setBreakingStrength(0) }} onDragEnd={handleDragEnd}>
      <div className="method-editor-tabs" role="tablist" aria-label="Method editor sections">
        <button type="button" role="tab" aria-selected={editorPane === 'source'} className={editorPane === 'source' ? 'active' : ''} onClick={() => setEditorPane('source')}><BookOpenText size={15}/>Source mapping</button>
        <button type="button" role="tab" aria-selected={editorPane === 'flow'} className={editorPane === 'flow' ? 'active' : ''} onClick={() => setEditorPane('flow')}><Layers3 size={15}/>Flow table</button>
      </div>
      <div className="method-editor-shell">
        <aside className="method-editor-guide">
          <p className="eyebrow">Review path</p>
          <ol><li className="done"><Check/>Ingredient mentions</li><li className={method.annotations.length ? 'done' : ''}><Check/>Semantic spans</li><li className={method.actions.length ? 'done' : ''}><Check/>Flow table rows</li><li className={data.method_status === 'reviewed' ? 'done' : ''}><Check/>Review and save</li></ol>
          <div className="method-editor-selection"><strong>Table editor</strong><span className="muted">Place every required ingredient, then review the warnings.</span></div>
          {lowConfidence > 0 && <Button variant="ghost" onClick={acceptSuggestions}><Check size={15}/>Accept {lowConfidence} suggestions</Button>}
        </aside>
        <section className={`method-source-editor method-editor-pane${editorPane === 'source' ? ' method-editor-pane--active' : ''}`}>
          <div className="method-section-heading"><div><span className="eyebrow">1 · Mark up the source</span><h2>Original written method</h2></div><Badge>{data.source_kind === 'publisher' ? 'Read-only source' : 'Editable source'}</Badge></div>
          {unreviewed > 0 && <div className="method-unreviewed" role="region" aria-labelledby="method-unreviewed-title">
            <div className="method-unreviewed__heading"><strong id="method-unreviewed-title">{unreviewed} unaccounted clause{unreviewed === 1 ? '' : 's'}</strong><span>Review the exact highlighted wording before saving this method.</span></div>
            {unresolvedClauses.length > 0 && <ol>{unresolvedClauses.map(({ annotation, text }, index) => <li key={annotation.id}><button type="button" onClick={() => {
              const target = document.getElementById(`unreviewed-clause-${annotation.id}`)
              target?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
              target?.focus({ preventScroll: true })
            }} aria-label={`Locate unaccounted clause ${index + 1}: ${text}`}><span aria-hidden="true">{index + 1}</span><strong>{text}</strong><Link2 size={14} aria-hidden="true"/></button></li>)}</ol>}
          </div>}
           {sourceBlocks.map((block, index) => <article className="method-source-block" key={block.id}>
             {block.heading && <h3>{block.heading}</h3>}
             {data.source_kind === 'publisher' ? <p ref={node => { sourceRefs.current[block.id] = node }} onPointerUp={() => captureSelection(block)}>{annotatedSource(block, method.annotations)}</p> : <textarea value={block.text} rows={5} onChange={event => { const text = event.target.value; setSourceBlocks(items => items.map((item, itemIndex) => itemIndex === index ? { ...item, text } : item)); setDirty(true) }}/>}
             <div className="method-source-tags">{method.annotations.filter(item => item.block_id === block.id).map(annotation => <button type="button" className={`semantic-chip semantic-chip--${annotation.kind}`} key={annotation.id} title="Remove this label" onClick={() => removeAnnotation(annotation.id)}><span>{annotation.kind}: {block.text.slice(annotation.start, annotation.end)}</span><X size={12}/></button>)}</div>
           </article>)}
           {!sourceBlocks.length && data.source_kind === 'table_only' && <article className="method-source-block method-source-block--empty"><h3>Add written instructions later</h3><p className="muted">The Flow table is already saved. Paste the original wording here whenever you want a Written view too.</p><textarea aria-label="Add written cooking method" rows={8} value={manualText} onChange={event => { const text = event.target.value; setManualText(text); setSourceBlocks([{ id: 'block-table-only', position: 0, text }]); setDirty(true) }} placeholder="Cook the potatoes until tender. Drain and serve."/></article>}
          {selection && <div className="semantic-toolbar" role="toolbar" aria-label="Mark selected recipe text"><div><strong>“{selection.text.slice(0, 56)}{selection.text.length > 56 ? '…' : ''}”</strong><span>What does this text mean?</span></div>{semanticTools.map(tool => { const Icon = tool.icon; return <button type="button" key={tool.kind} onClick={() => tagSelection(tool.kind)}><Icon size={15}/>{tool.label}</button> })}<button type="button" onClick={() => { updateDocument(current => ({ ...current, omissions: [...current.omissions, { id: localId('omission'), block_id: selection.blockId, start: selection.start, end: selection.end, reason: 'Omitted from concise summary', accepted: true }] })); setSelection(null) }}><Trash2 size={15}/>Omit</button>{annotationIngredient && <select aria-label="Ingredient for selected text" value={annotationIngredient} onChange={event => setAnnotationIngredient(event.target.value)}>{data.ingredients.map(item => <option key={item.lineage_id} value={item.lineage_id}>{item.name}</option>)}</select>}</div>}
        </section>
        <section className={`method-canvas-editor method-editor-pane${editorPane === 'flow' ? ' method-editor-pane--active' : ''}`}>
          <div className="method-section-heading"><div><span className="eyebrow">2 · Arrange the flow</span><h2>Flow table</h2></div><Badge tone="blue">Canonical visual editor</Badge></div>
          {table && <RecipeFlowTable data={{ ...data, table: data.table ?? { status: 'needs_review', coverage: { total_actions: method.actions.length, represented_actions: method.actions.length, total_included_ingredient_lineages: data.ingredients.length, represented_ingredient_lineages: 0, ingredient_use_rows: method.ingredient_bindings.filter(binding => binding.role !== 'reference').length, explicitly_omitted_ingredients: 0, explicitly_omitted_actions: 0, unplaced_ingredients: data.ingredients.length, disconnected_components: 0, low_confidence_labels: 0, low_confidence_bindings: 0, low_confidence_edges: 0, blocking_warnings: 0, non_blocking_warnings: 0 }, document: table, rendered_ingredient_uses: [], warnings: [] } }} method={method} table={table} editable onTableChange={next => { setTable(next); setDirty(true) }} onMethodChange={next => { setMethod(next); setDirty(true) }}/>}
          <div className="flow-editor-save-row"><Button type="button" variant="secondary" disabled={savePending !== null} onClick={() => void saveTable(false)}><Save size={16}/>{savePending === 'draft' ? 'Saving…' : 'Save flow draft'}</Button><Button type="button" disabled={savePending !== null || Boolean(conflictLatest) || Number(data.table?.coverage.blocking_warnings ?? 0) > 0} title={Number(data.table?.coverage.blocking_warnings ?? 0) > 0 ? 'Resolve the Flow table warnings before reviewing it.' : undefined} onClick={() => void saveTable(true)}><Check size={16}/>{savePending === 'review' ? 'Saving…' : 'Mark flow table reviewed'}</Button></div>
        </section>
        <section className="method-editor-save"><label>Household notes<textarea rows={3} value={notes} onChange={event => { setNotes(event.target.value); setDirty(true) }} placeholder="Add adaptations or reminders without changing the publisher wording."/></label><div><Button type="button" variant="secondary" disabled={savePending !== null} onClick={() => void saveMethod(false)}><Save size={16}/>{savePending === 'draft' ? 'Saving…' : 'Save draft'}</Button><Button type="button" disabled={reviewBlocked || savePending !== null || Boolean(conflictLatest)} onClick={() => void saveMethod(true)}><Check size={16}/>{savePending === 'review' ? 'Saving…' : 'Mark as reviewed'}</Button></div></section>
      </div>
      <DragOverlay>{activeDrag && <div className={`method-drag-overlay method-drag-overlay--${activeDrag.type}`}><GripVertical size={15}/>{activeDrag.label}</div>}</DragOverlay>
    </DndContext> : view === 'summary' ? <MethodSummary data={data}/> : view === 'table' ? <RecipeFlowTable data={data} method={method} table={table ?? draftTableDocument(method)}/> : <WrittenMethod data={data}/>}

    {pendingPlacement && <div className="modal-backdrop" role="presentation"><Card className="flow-placement-dialog" role="dialog" aria-modal="true" aria-labelledby="flow-placement-title"><div><p className="eyebrow">Repeated ingredient use</p><h2 id="flow-placement-title">How much enters this operation?</h2><p>{data.ingredients.find(item => item.lineage_id === pendingPlacement.lineageId)?.name ?? 'Ingredient'} already has a row. Keep the use explicit so the table never hides a quantity.</p><label>Fraction or absolute amount<input aria-label="Portion amount" type="number" min="0.01" step="0.01" value={placementAmount} onChange={event => setPlacementAmount(event.target.value)}/></label><div className="button-row"><Button variant="ghost" onClick={() => setPendingPlacement(null)}>Cancel</Button><Button variant="secondary" onClick={() => chooseIngredientPlacement('all')}>Use all</Button><Button variant="secondary" onClick={() => chooseIngredientPlacement('fraction')}>Use a fraction</Button><Button variant="secondary" onClick={() => chooseIngredientPlacement('absolute')}>Use an absolute amount</Button><Button onClick={() => chooseIngredientPlacement('remainder')}>Use the remainder</Button></div></div></Card></div>}
    {conflictLatest && <div className="modal-backdrop" role="presentation"><Card className="method-conflict" role="dialog" aria-modal="true" aria-labelledby="method-conflict-title"><AlertTriangle/><div><p className="eyebrow">Version conflict</p><h2 id="method-conflict-title">Someone saved this method first</h2><p>Your local draft is safe. The latest version has {conflictLatest.method.actions.length} actions; yours has {method.actions.length}.</p><div className="button-row"><Button variant="secondary" onClick={() => { setData(conflictLatest); setMethod(structuredClone(conflictLatest.method)); setSourceBlocks(structuredClone(conflictLatest.source_blocks)); setDirty(false); setConflictLatest(null) }}>Load latest</Button><Button onClick={() => { setData(current => current ? { ...current, recipe_version: conflictLatest.recipe_version } : current); setConflictLatest(null); setMessage('Your draft is ready to reapply over the latest version.') }}>Reapply my draft</Button></div></div></Card></div>}
    {refreshCandidate && <div className="modal-backdrop" role="presentation"><Card className="method-refresh-dialog" role="dialog" aria-modal="true" aria-labelledby="method-refresh-title"><RefreshCw/><div><p className="eyebrow">Source comparison</p><h2 id="method-refresh-title">{refreshCandidate.refresh_diff?.changed ? 'The publisher method changed' : 'The publisher method is unchanged'}</h2><p>{refreshCandidate.refresh_diff?.changed ? `The saved method has ${refreshCandidate.refresh_diff.old_block_count ?? 0} source blocks; the current page has ${refreshCandidate.refresh_diff.new_block_count ?? 0}. Applying creates a new immutable recipe version and keeps your history intact.` : 'Your saved source checksum matches the current page. No update is needed.'}</p><div className="button-row"><Button variant="ghost" onClick={() => setRefreshCandidate(null)}>Close</Button>{refreshCandidate.refresh_diff?.changed && <Button disabled={applyRefresh.isPending} onClick={() => applyRefresh.mutate()}><RefreshCw className={applyRefresh.isPending ? 'spin' : ''} size={16}/>{applyRefresh.isPending ? 'Applying…' : 'Apply as new draft'}</Button>}</div></div></Card></div>}
    {tutorialStep != null && <Tutorial step={tutorialStep} setStep={setTutorialStep} dismiss={dismissTutorial}/>}
  </div>
}

function MethodSummary({ data }: { data: BackendMethodView }) {
  const method = data.method
  const ingredients = new Map(data.ingredients.map(item => [item.lineage_id, item]))
  return <div className="method-view-grid">
    <aside className="method-ingredients-panel"><div className="method-panel-heading"><span>Ingredient rail</span><Badge>{data.ingredients.length}</Badge></div><ol>{data.ingredients.map(item => <li key={item.lineage_id}><span>{item.quantity_text} {item.unit}</span><strong>{item.name}</strong>{item.preparation && <small>{item.preparation}</small>}</li>)}</ol></aside>
    <main className="method-summary-board">{[...method.stages].sort((a,b) => a.position-b.position).map((stage, stageIndex) => {
      const actions = method.actions.filter(item => item.stage_id === stage.id).sort((a,b) => a.position-b.position)
      return <section className="method-summary-stage" key={stage.id}><header><span>{String(stageIndex + 1).padStart(2, '0')}</span><h2>{stage.title}</h2></header><div className="method-action-flow">{actions.map((action, index) => {
        const inputs = method.ingredient_bindings.filter(item => item.action_id === action.id).map(binding => {
          const ingredient = ingredients.get(binding.ingredient_lineage_id)
          return ingredient ? { binding, ingredient } : null
        }).filter(Boolean) as { binding: BackendMethodBinding; ingredient: BackendMethodIngredient }[]
        const incoming = method.edges.filter(edge => edge.to_action_id === action.id)
        return <div className="method-summary-step" key={action.id}>{index > 0 && <span className="method-flow-line"/>}{incoming.some(edge => edge.kind === 'merge') && <Badge tone="warm"><Layers3 size={12}/>Merge</Badge>}<div className="method-inputs">{inputs.map(({ binding, ingredient }) => <span key={binding.id}>{bindingIngredientQuantity(binding, ingredient, method.ingredient_bindings)} {binding.portion_unit ?? ingredient.unit} <b>{ingredient.name}</b></span>)}</div><strong>{action.text}</strong><div className="method-action-meta">{action.duration_minutes != null && <span><Clock3/>{action.duration_minutes} min</span>}{action.temperature_value != null && <span><Thermometer/>{action.temperature_value}°{action.temperature_unit?.toUpperCase()}</span>}{action.equipment.map(item => <span key={item}><Utensils/>{item}</span>)}</div>{action.cue && <small>Ready when {action.cue}</small>}</div>
      })}</div></section>
    })}</main>
  </div>
}

function bindingIngredientQuantity(binding: BackendMethodBinding, ingredient: BackendMethodIngredient, bindings: BackendMethodBinding[]) {
  const baseQuantity = ingredient.quantity == null ? undefined : Number(ingredient.quantity)
  if (binding.portion_mode === 'absolute' && binding.portion_value != null) return displayMethodNumber(Number(binding.portion_value))
  if (baseQuantity == null) return ingredient.quantity_text ?? ''
  if (binding.portion_mode === 'fraction' && binding.portion_value != null) return displayMethodNumber(baseQuantity * Number(binding.portion_value))
  if (binding.portion_mode === 'remainder') {
    const usedFraction = bindings
      .filter(item => item.ingredient_lineage_id === binding.ingredient_lineage_id && item.portion_mode === 'fraction')
      .reduce((total, item) => total + Number(item.portion_value ?? 0), 0)
    return displayMethodNumber(baseQuantity * Math.max(0, 1 - usedFraction))
  }
  return ingredient.quantity_text ?? displayMethodNumber(baseQuantity)
}

function displayMethodNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value)
}

function WrittenMethod({ data }: { data: BackendMethodView }) {
  return <div className="written-method-layout"><aside className="method-ingredients-panel"><div className="method-panel-heading"><span>For {data.requested_servings ?? data.base_servings ?? 'the recipe'}</span><Badge>{data.ingredients.length} ingredients</Badge></div><ol>{data.ingredients.map(item => <li key={item.lineage_id}><span>{item.quantity_text} {item.unit}</span><strong>{item.name}</strong></li>)}</ol></aside><main className="written-method"><div className="written-method-key"><span><i className="semantic-dot semantic-dot--ingredient"/>Linked ingredient</span><span>Quantities update with the batch</span></div>{data.rendered_blocks.length ? data.rendered_blocks.map((block, index) => <article key={block.id}><span className="written-step-number">{String(index + 1).padStart(2,'0')}</span><div>{block.heading && <h2>{block.heading}</h2>}<p>{block.segments.map((segment, segmentIndex) => segment.kind === 'ingredient' ? <mark className="written-ingredient" key={segmentIndex}>{segment.text}{segment.quantity_label && <small>{segment.quantity_label}</small>}</mark> : <span key={segmentIndex}>{segment.text}</span>)}</p></div></article>) : <div className="written-empty-state"><PencilLine size={20}/><strong>No written method was supplied</strong><p>This recipe has a Flow table only. Switch to Flow table to cook from the saved operations, or add written instructions in the editor.</p></div>}{data.household_notes && <Card className="method-household-notes"><strong>Household notes</strong><p>{data.household_notes}</p></Card>}</main></div>
}

function DraggableIngredient({ ingredient, selected, onSelect }: { ingredient: BackendMethodIngredient; selected: boolean; onSelect: () => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `ingredient:${ingredient.lineage_id}`, data: { type: 'ingredient', label: ingredient.name } })
  return <button ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform) }} className={`method-ingredient-chip${selected ? ' selected' : ''}${isDragging ? ' is-dragging' : ''}`} type="button" onClick={onSelect} {...listeners} {...attributes}><GripVertical size={13}/><span>{ingredient.quantity_text} {ingredient.unit}</span><strong>{ingredient.name}</strong></button>
}

function DroppableStage({ stage, actions, method, ingredients, selectedActions, setSelectedActions, updateDocument, breakingAction, breakingStrength, justGrouped }: { stage: BackendMethodStage; actions: BackendMethodAction[]; method: BackendMethodDocument; ingredients: BackendMethodIngredient[]; selectedActions: Set<string>; setSelectedActions: Dispatch<SetStateAction<Set<string>>>; updateDocument: (updater: (current: BackendMethodDocument) => BackendMethodDocument) => void; breakingAction: string | null; breakingStrength: number; justGrouped: string | null }) {
  const { setNodeRef, isOver } = useDroppable({ id: `stage:${stage.id}`, data: { type: 'stage' } })
  return <section ref={setNodeRef} className={`method-canvas-stage${isOver ? ' is-over' : ''}`}><header><input aria-label="Stage name" value={stage.title} onChange={event => updateDocument(current => ({ ...current, stages: current.stages.map(item => item.id === stage.id ? { ...item, title: event.target.value } : item) }))}/><Badge>{actions.length} steps</Badge></header><SortableContext items={actions.map(action => `action:${action.id}`)} strategy={verticalListSortingStrategy}>{actions.map(action => <SortableAction key={action.id} action={action} method={method} ingredients={ingredients} selected={selectedActions.has(action.id)} onSelect={() => setSelectedActions(current => { const next = new Set(current); next.has(action.id) ? next.delete(action.id) : next.add(action.id); return next })} updateDocument={updateDocument} breaking={breakingAction === `action:${action.id}`} breakingStrength={breakingStrength} grouped={justGrouped === action.id}/>)}</SortableContext>{!actions.length && <div className="method-stage-drop-hint">Drop actions here to build a parallel lane</div>}</section>
}

function SortableAction({ action, method, ingredients, selected, onSelect, updateDocument, breaking, breakingStrength, grouped }: { action: BackendMethodAction; method: BackendMethodDocument; ingredients: BackendMethodIngredient[]; selected: boolean; onSelect: () => void; updateDocument: (updater: (current: BackendMethodDocument) => BackendMethodDocument) => void; breaking: boolean; breakingStrength: number; grouped: boolean }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging, isOver } = useSortable({ id: `action:${action.id}`, data: { type: 'action', label: action.text } })
  const ingredientMap = new Map(ingredients.map(item => [item.lineage_id, item]))
  const bindings = method.ingredient_bindings.filter(item => item.action_id === action.id)
  const breakClass = breaking ? (breakingStrength > .72 ? ' is-breaking is-breaking--hard' : breakingStrength > .32 ? ' is-breaking is-breaking--medium' : ' is-breaking') : ''
  return <article ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={`method-action-card${selected ? ' selected' : ''}${isDragging ? ' is-dragging' : ''}${isOver ? ' is-over' : ''}${breakClass}${grouped ? ' just-grouped' : ''}`} onClick={onSelect}><button type="button" className="method-drag-handle" aria-label={`Move ${action.text}`} {...listeners} {...attributes}><GripVertical/></button><div className="method-action-inputs">{bindings.map(binding => { const ingredient = ingredientMap.get(binding.ingredient_lineage_id); return ingredient && <span key={binding.id}>{ingredient.name}<button type="button" aria-label={`Remove ${ingredient.name} from ${action.text}`} onClick={event => { event.stopPropagation(); updateDocument(current => ({ ...current, ingredient_bindings: current.ingredient_bindings.filter(item => item.id !== binding.id) })) }}><X/></button></span> })}</div><textarea aria-label="Action text" rows={2} value={action.text} onClick={event => event.stopPropagation()} onChange={event => updateDocument(current => ({ ...current, actions: current.actions.map(item => item.id === action.id ? { ...item, text: event.target.value } : item) }))}/><div className="method-action-properties">{action.duration_minutes != null && <span><Clock3/>{action.duration_minutes} min</span>}{action.temperature_value != null && <span><Thermometer/>{action.temperature_value}°{action.temperature_unit?.toUpperCase()}</span>}{action.cue && <span><Check/>{action.cue}</span>}</div></article>
}

function Tutorial({ step, setStep, dismiss }: { step: number; setStep: (step: number | null) => void; dismiss: () => Promise<void> }) {
  const slides = [
    { icon: MousePointer2, title: 'Tag the source', copy: 'Select a phrase, then label it as an ingredient, action, time, temperature, equipment or doneness cue.' },
    { icon: Layers3, title: 'Place ingredients in the table', copy: 'Drag an ingredient from the Unplaced tray onto an operation. Repeated uses stay as separate scaled rows, so the quantities remain honest.' },
    { icon: Split, title: 'Shape branches and merges', copy: 'Use the Before, After, or Merge into drop zones to keep parallel preparations separate until the moment they combine.' },
  ]
  const slide = slides[step]
  const Icon = slide.icon
  return <div className="method-tutorial-backdrop" role="presentation"><Card className="method-tutorial" role="dialog" aria-modal="true" aria-labelledby="method-tutorial-title"><button type="button" className="modal-close" aria-label="Dismiss tutorial" onClick={() => void dismiss()}><X/></button><div className="method-tutorial-visual"><Icon/></div><p className="eyebrow">Quick tour · {step + 1}/{slides.length}</p><h2 id="method-tutorial-title">{slide.title}</h2><p>{slide.copy}</p><div className="method-tutorial-dots">{slides.map((_, index) => <i className={index === step ? 'active' : ''} key={index}/>)}</div><div className="button-row"><Button variant="ghost" onClick={() => void dismiss()}>Dismiss</Button>{step < slides.length - 1 ? <Button onClick={() => setStep(step + 1)}>Next</Button> : <Button onClick={() => void dismiss()}><Check size={16}/>Start editing</Button>}</div></Card></div>
}
