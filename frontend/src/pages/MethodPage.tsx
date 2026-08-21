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
  Check,
  CircleHelp,
  Clock3,
  ExternalLink,
  Flame,
  GripVertical,
  Layers3,
  Link2,
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
  type ApiAction,
  isDemoMode,
  type BackendMethodAction,
  type BackendMethodAnnotation,
  type BackendMethodBinding,
  type BackendMethodDocument,
  type BackendMethodIngredient,
  type BackendMethodSourceBlock,
  type BackendMethodStage,
  type BackendMethodView,
  type BackendRecipeDetail,
  type MethodSemanticKind,
} from '../api/client'
import { MealTypePicker, type RecipeMealType } from '../components/MealTypePicker'
import { Badge, Button, Card, Loading, Notice, PageHeader } from '../components/ui'
import { safeExternalUrl } from '../lib/safeUrls'

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
type SourceRange = {
  blockId: string
  start: number
  end: number
  text: string
}

function historicalRecoveryAction(error: unknown): ApiAction | undefined {
  if (!(error instanceof ApiError) || error.code !== 'HISTORICAL_METHOD_NOT_CAPTURED') return undefined
  return error.actions.find(action => action.kind === 'recover_historical_method')
}

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

const annotationPriority: Record<MethodSemanticKind, number> = {
  ingredient: 0,
  time: 1,
  temperature: 2,
  equipment: 3,
  cue: 4,
  action: 5,
}

type AnnotatedSourcePart = {
  start: number
  end: number
  text: string
  annotation?: BackendMethodAnnotation
  unreviewed?: BackendMethodAnnotation
}

function annotatedSourceParts(block: BackendMethodSourceBlock, annotations: BackendMethodAnnotation[]) {
  const valid = annotations.filter(item => (
    item.block_id === block.id
    && item.start >= 0
    && item.end <= block.text.length
    && item.end > item.start
  ))
  const boundaries = [...new Set([0, block.text.length, ...valid.flatMap(item => [item.start, item.end])])]
    .sort((left, right) => left - right)
  const parts: AnnotatedSourcePart[] = []
  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index]
    const end = boundaries[index + 1]
    if (end <= start) continue
    const covering = valid.filter(item => item.start <= start && item.end >= end)
    const annotation = [...covering].sort((left, right) => (
      annotationPriority[left.kind] - annotationPriority[right.kind]
      || (left.end - left.start) - (right.end - right.start)
    ))[0]
    const unreviewed = covering.find(isUnreviewedClause)
    const previous = parts.at(-1)
    if (previous && previous.annotation?.id === annotation?.id && previous.unreviewed?.id === unreviewed?.id) {
      previous.end = end
      previous.text += block.text.slice(start, end)
    } else {
      parts.push({ start, end, text: block.text.slice(start, end), annotation, unreviewed })
    }
  }
  return parts
}

function sourceTokens(text: string, offset: number) {
  const tokens: Array<{ text: string; start: number; end: number; word: boolean }> = []
  const words = text.matchAll(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu)
  let cursor = 0
  for (const match of words) {
    const start = match.index ?? 0
    if (start > cursor) tokens.push({ text: text.slice(cursor, start), start: offset + cursor, end: offset + start, word: false })
    tokens.push({ text: match[0], start: offset + start, end: offset + start + match[0].length, word: true })
    cursor = start + match[0].length
  }
  if (cursor < text.length) tokens.push({ text: text.slice(cursor), start: offset + cursor, end: offset + text.length, word: false })
  return tokens
}

function DroppableSourceWord({ blockId, token, linkIngredientId, linkIngredientName, onLink }: {
  blockId: string
  token: { text: string; start: number; end: number }
  linkIngredientId?: string
  linkIngredientName?: string
  onLink: (range: SourceRange) => void
}) {
  const range = { blockId, start: token.start, end: token.end, text: token.text }
  const { setNodeRef, isOver } = useDroppable({
    id: `source-word:${blockId}:${token.start}:${token.end}`,
    data: { type: 'source-word', ...range },
  })
  const linkable = Boolean(linkIngredientId)
  const link = () => { if (linkable) onLink(range) }
  return <span
    ref={setNodeRef}
    className={`method-source-word${linkable ? ' is-link-target' : ''}${isOver && linkable ? ' is-over' : ''}`}
    role={linkable ? 'button' : undefined}
    tabIndex={linkable ? 0 : undefined}
    aria-label={linkable ? `Link ${linkIngredientName ?? 'ingredient'} to “${token.text}”` : undefined}
    onClick={linkable ? event => { event.stopPropagation(); link() } : undefined}
    onKeyDown={linkable ? event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        link()
      }
    } : undefined}
  >{token.text}</span>
}

function annotatedSource(
  block: BackendMethodSourceBlock,
  annotations: BackendMethodAnnotation[],
  linkIngredientId: string | undefined,
  linkIngredientName: string | undefined,
  onLink: (range: SourceRange) => void,
) {
  return annotatedSourceParts(block, annotations).map((part, index) => {
    const content = sourceTokens(part.text, part.start).map((token, tokenIndex) => token.word
      ? <DroppableSourceWord key={`${token.start}-${token.end}`} blockId={block.id} token={token} linkIngredientId={linkIngredientId} linkIngredientName={linkIngredientName} onLink={onLink}/>
      : <span key={`separator-${tokenIndex}`}>{token.text}</span>)
    if (!part.annotation && !part.unreviewed) return <span key={`text-${index}`}>{content}</span>
    const annotation = part.annotation ?? part.unreviewed!
    const unreviewed = part.unreviewed
    const isWarningTarget = Boolean(unreviewed && part.start === unreviewed.start)
    return <mark
      key={`${annotation.id}-${part.start}`}
      id={isWarningTarget ? `unreviewed-clause-${unreviewed!.id}` : undefined}
      data-unreviewed-clause={isWarningTarget ? 'true' : undefined}
      tabIndex={isWarningTarget ? -1 : undefined}
      className={`semantic-mark semantic-mark--${annotation.kind}${annotation.accepted ? ' accepted' : ''}${unreviewed ? ' semantic-mark--unreviewed' : ''}`}
      title={unreviewed ? 'Unaccounted source clause' : `${annotation.kind}${annotation.confidence < REVIEW_CONFIDENCE_THRESHOLD ? ' · check this suggestion' : ''}`}
      aria-label={isWarningTarget ? `Unaccounted source clause: ${block.text.slice(unreviewed!.start, unreviewed!.end)}` : undefined}
    >{content}</mark>
  })
}

function actionForSourceRange(
  document: BackendMethodDocument,
  blocks: BackendMethodSourceBlock[],
  target: SourceRange,
) {
  const annotations = new Map(document.annotations.map(item => [item.id, item]))
  const candidates = document.actions.flatMap(action => action.source_annotation_ids
    .map(id => annotations.get(id))
    .filter((item): item is BackendMethodAnnotation => Boolean(item && item.block_id === target.blockId))
    .map(annotation => ({ action, annotation })))
  const containing = candidates
    .filter(({ annotation }) => annotation.start <= target.start && annotation.end >= target.end)
    .sort((left, right) => (left.annotation.end - left.annotation.start) - (right.annotation.end - right.annotation.start))
  if (containing[0]) return containing[0].action

  const block = blocks.find(item => item.id === target.blockId)
  if (block) {
    const lowered = block.text.toLocaleLowerCase()
    const textMatch = document.actions.find(action => {
      const start = lowered.indexOf(action.text.toLocaleLowerCase())
      return start >= 0 && start <= target.start && start + action.text.length >= target.end
    })
    if (textMatch) return textMatch
  }
  return document.actions.length === 1 ? document.actions[0] : undefined
}

function validSplitPosition(text: string, index: number | null) {
  if (index == null || index <= 0 || index >= text.length) return false
  if (!text.slice(0, index).trim() || !text.slice(index).trim()) return false
  return /[\s,;.!?]/.test(text[index - 1]) || /[\s,;.!?]/.test(text[index])
}

function manualDocument(text: string, blockId = 'block-1'): { blocks: BackendMethodSourceBlock[]; method: BackendMethodDocument } {
  const trimmedText = text.trim()
  const block: BackendMethodSourceBlock = { id: blockId, position: 0, text: trimmedText }
  const clauses = [...trimmedText.matchAll(/[^.!?;\n]+(?:[.!?;]+|$)/g)].filter(match => match[0].trim())
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
  const [servingsDraft, setServingsDraft] = useState<string | null>(null)
  const servingsInputRef = useRef<HTMLInputElement>(null)
  const servingRequestRef = useRef<{ previous: number | undefined; requested: number } | null>(null)
  const preserveServingDraftRef = useRef(false)
  const [servingPending, setServingPending] = useState(false)
  const [servingError, setServingError] = useState('')
  const methodQueryKey = preview ? ['method-preview', sourceUrl] : ['recipe-method', recipeId, batchId, servings]
  const methodQuery = useQuery({
    queryKey: methodQueryKey,
    queryFn: () => preview ? api.methodPreview(sourceUrl) : api.getRecipeMethod(recipeId!, { batchId, servings }),
    enabled: !isDemoMode && (preview ? Boolean(sourceUrl) : Boolean(recipeId)),
    retry: false,
  })
  const [data, setData] = useState<BackendMethodView | null>(null)
  const [method, setMethod] = useState<BackendMethodDocument | null>(null)
  const [sourceBlocks, setSourceBlocks] = useState<BackendMethodSourceBlock[]>([])
  const [notes, setNotes] = useState('')
  const [editing, setEditing] = useState(false)
  const [savePending, setSavePending] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [manualText, setManualText] = useState('')
  const [mealTypes, setMealTypes] = useState<RecipeMealType[]>([])
  const [selectedIngredients, setSelectedIngredients] = useState<Set<string>>(new Set())
  const [selectedActions, setSelectedActions] = useState<Set<string>>(new Set())
  const [selection, setSelection] = useState<SourceRange | null>(null)
  const [annotationIngredient, setAnnotationIngredient] = useState('')
  const [sourceEditBlockId, setSourceEditBlockId] = useState<string | null>(null)
  const [activeDrag, setActiveDrag] = useState<{ id: string; type: 'ingredient' | 'action'; label: string } | null>(null)
  const [breakingAction, setBreakingAction] = useState<string | null>(null)
  const [breakingStrength, setBreakingStrength] = useState(0)
  const [justGrouped, setJustGrouped] = useState<string | null>(null)
  const [tutorialStep, setTutorialStep] = useState<number | null>(null)
  const [conflictLatest, setConflictLatest] = useState<BackendMethodView | null>(null)
  const [refreshCandidate, setRefreshCandidate] = useState<BackendMethodView | null>(null)

  useEffect(() => {
    if ((session.data?.method_tutorial_version_seen ?? TUTORIAL_VERSION) < TUTORIAL_VERSION) setTutorialStep(0)
  }, [session.data?.method_tutorial_version_seen])
  useEffect(() => {
    if (!methodQuery.data || dirty) return
    setData(methodQuery.data)
    setMethod(structuredClone(methodQuery.data.method))
    setSourceBlocks(structuredClone(methodQuery.data.source_blocks))
    setNotes(methodQuery.data.household_notes ?? '')
    setAnnotationIngredient(methodQuery.data.ingredients[0]?.lineage_id ?? '')
    const request = servingRequestRef.current
    const responseServings = methodQuery.data.requested_servings == null ? undefined : Number(methodQuery.data.requested_servings)
    if (request && responseServings === request.requested) {
      servingRequestRef.current = null
      setServingPending(false)
    }
    if (!preserveServingDraftRef.current && document.activeElement !== servingsInputRef.current) {
      setServingsDraft(methodQuery.data.requested_servings == null ? '' : String(methodQuery.data.requested_servings))
    }
    preserveServingDraftRef.current = false
  }, [methodQuery.data, dirty])

  useEffect(() => {
    const request = servingRequestRef.current
    if (!request || !methodQuery.error) return
    servingRequestRef.current = null
    preserveServingDraftRef.current = true
    setServings(request.previous)
    setServingPending(false)
    setServingError(methodQuery.error instanceof Error ? methodQuery.error.message : 'The serving count could not be loaded. Try again.')
  }, [methodQuery.error])

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
      setData(result); setMethod(structuredClone(result.method)); setSourceBlocks(structuredClone(result.source_blocks)); setRefreshCandidate(null); setDirty(false)
      setMessage('The latest source method is ready for review.')
      void queryClient.invalidateQueries({ queryKey: ['recipes'] })
    },
    onError: reason => setError(reason instanceof Error ? reason.message : 'The refreshed method could not be applied.'),
  })
  const recoverHistorical = useMutation({
    mutationFn: () => {
      if (!recipeId || !batchId) throw new Error('This recovery action needs a meal batch.')
      return api.recoverHistoricalRecipeMethod(recipeId, batchId)
    },
    onSuccess: result => {
      queryClient.setQueryData(methodQueryKey, result)
      setData(result)
      setMethod(structuredClone(result.method))
      setSourceBlocks(structuredClone(result.source_blocks))
      setNotes(result.household_notes ?? '')
      setDirty(false)
      setServingError('')
      setMessage('The current method was captured for this historical batch. The cooked record and batch ingredients were unchanged.')
      void queryClient.invalidateQueries({ queryKey: ['recipes'] })
    },
    onError: reason => setServingError(reason instanceof Error ? reason.message : 'The historical method could not be captured.'),
  })

  const saveMethod = async () => {
    if (!recipeId || preview || !method || !data?.recipe_version || savePending) return
    setSavePending(true)
    setError(''); setMessage('')
    try {
      const result = await api.saveRecipeMethod(recipeId, {
        expected_version: data.recipe_version,
        method,
        household_notes: notes || undefined,
        mark_reviewed: true,
        source_kind: data.source_kind as 'custom' | 'publisher' | 'manual_paste',
        source_blocks: data.source_kind === 'publisher' ? undefined : sourceBlocks,
      })
      queryClient.setQueryData(methodQueryKey, result)
      setData(result); setMethod(structuredClone(result.method)); setSourceBlocks(structuredClone(result.source_blocks)); setDirty(false); setEditing(false)
      setMessage('Method saved and reviewed.')
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
      setSavePending(false)
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
  }

  const updateDocument = (updater: (current: BackendMethodDocument) => BackendMethodDocument) => {
    setMethod(current => current ? updater(current) : current)
    setDirty(true)
  }

  const servingValue = servingsDraft ?? (data?.requested_servings == null ? '' : String(servings ?? data.requested_servings))
  const currentServingValue = servingPending
    ? servingRequestRef.current?.previous ?? data?.requested_servings
    : servings ?? data?.requested_servings
  const servingDraftNumber = servingValue.trim() ? Number(servingValue) : undefined
  const servingDraftChanged = servingsDraft != null && (
    servingValue.trim() === ''
      ? currentServingValue != null
      : !Number.isFinite(servingDraftNumber) || servingDraftNumber !== currentServingValue
  )
  const requestServings = (next: number) => {
    if (currentServingValue === next) {
      setServingError('')
      return
    }
    servingRequestRef.current = { previous: servings, requested: next }
    setServingError('')
    setServingPending(true)
    setServings(next)
  }
  const commitServings = () => {
    if (servingsDraft == null) return
    const raw = servingsDraft.trim()
    if (!raw) {
      if (data?.base_servings == null) {
        setServingError('Enter a serving count greater than zero.')
        return
      }
      requestServings(Number(data.base_servings))
      return
    }
    const next = Number(raw)
    if (!Number.isFinite(next) || next <= 0) {
      setServingError('Enter a serving count greater than zero.')
      return
    }
    requestServings(next)
  }
  const recoveryAction = historicalRecoveryAction(methodQuery.error)
  const recoveryActionView = recoveryAction && batchId ? <div className="method-recovery-action">
    <small>{recoveryAction.suggestion ?? 'Copy the current saved method onto this historical batch to continue.'}</small>
    <Button type="button" variant="secondary" disabled={recoverHistorical.isPending} onClick={() => recoverHistorical.mutate()}>
      {recoverHistorical.isPending ? 'Capturing…' : recoveryAction.label ?? 'Use current method for this batch'}
    </Button>
  </div> : null
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
  const linkIngredientToSourceRange = (lineageId: string, target: SourceRange) => {
    if (!method || !data) return
    const ingredient = data.ingredients.find(item => item.lineage_id === lineageId)
    const action = actionForSourceRange(method, sourceBlocks, target)
    if (!ingredient || !action) {
      setError('This word is not inside a cooking step. Tag the step as an action first, then try again.')
      return
    }
    const overlapping = method.annotations.find(item => (
      item.kind === 'ingredient'
      && item.block_id === target.blockId
      && item.start < target.end
      && item.end > target.start
    ))
    updateDocument(current => {
      const existingBinding = current.ingredient_bindings.find(item => (
        item.action_id === action.id && item.ingredient_lineage_id === lineageId
      ))
      const annotationId = overlapping?.id ?? localId('annotation')
      const replacedAnnotationIds = new Set(
        [overlapping?.id, existingBinding?.annotation_id].filter((id): id is string => Boolean(id)),
      )
      const annotation: BackendMethodAnnotation = {
        id: annotationId,
        block_id: target.blockId,
        start: target.start,
        end: target.end,
        kind: 'ingredient',
        origin: 'user',
        confidence: 1,
        accepted: true,
        ingredient_lineage_id: lineageId,
      }
      return {
        ...current,
        annotations: [
          ...current.annotations.filter(item => !replacedAnnotationIds.has(item.id)),
          annotation,
        ],
        ingredient_bindings: [
          ...current.ingredient_bindings.filter(item => (
            item.id !== existingBinding?.id
            && !(item.annotation_id && replacedAnnotationIds.has(item.annotation_id))
          )),
          {
            ...existingBinding,
            id: existingBinding?.id ?? localId('binding'),
            action_id: action.id,
            ingredient_lineage_id: lineageId,
            annotation_id: annotationId,
            portion_mode: existingBinding?.portion_mode ?? 'unspecified',
            confidence: 1,
            accepted: true,
          },
        ],
      }
    })
    setSelectedIngredients(new Set())
    setAnnotationIngredient(lineageId)
    setError('')
    setMessage(`Linked ${ingredient.name} to “${target.text}”. Save the method to update the written view.`)
  }

  const finishSourceTextEdit = (blockId: string) => {
    const block = sourceBlocks.find(item => item.id === blockId)
    if (!block?.text.trim()) {
      setError('Write some method text before finishing the wording edit.')
      return
    }
    if (sourceBlocks.length === 1) {
      const generated = manualDocument(block.text, block.id)
      setMethod(generated.method)
      setMessage('Wording updated. Re-link any ingredients whose words changed.')
    }
    setSourceEditBlockId(null)
    setSelection(null)
    setError('')
    setDirty(true)
  }

  const tagSelection = (kind: MethodSemanticKind) => {
    if (!selection || !method) return
    if (kind === 'ingredient') {
      if (annotationIngredient) linkIngredientToSourceRange(annotationIngredient, selection)
      window.getSelection()?.removeAllRanges(); setSelection(null)
      return
    }
    const annotation: BackendMethodAnnotation = {
      id: localId('annotation'), block_id: selection.blockId, start: selection.start, end: selection.end,
      kind, origin: 'user', confidence: 1, accepted: true,
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

  const attachIngredient = (lineageId: string, actionId: string) => {
    updateDocument(current => current.ingredient_bindings.some(item => item.action_id === actionId && item.ingredient_lineage_id === lineageId) ? current : ({
      ...current,
      ingredient_bindings: [...current.ingredient_bindings, { id: localId('binding'), action_id: actionId, ingredient_lineage_id: lineageId, portion_mode: 'unspecified', confidence: 1, accepted: true }],
    }))
    setJustGrouped(actionId); window.setTimeout(() => setJustGrouped(value => value === actionId ? null : value), 520)
  }
  const splitAction = (actionId: string, splitAt: number) => {
    updateDocument(current => {
      const action = current.actions.find(item => item.id === actionId)
      if (!action || !validSplitPosition(action.text, splitAt)) return current

      const leftText = action.text.slice(0, splitAt).trim()
      const rightText = action.text.slice(splitAt).trim()
      const newActionId = localId('action')
      let annotations = [...current.annotations]
      let rightSourceAnnotationIds = [...action.source_annotation_ids]
      let sourceBoundary: { blockId: string; index: number } | undefined

      for (const annotationId of action.source_annotation_ids) {
        const annotation = current.annotations.find(item => item.id === annotationId && item.kind === 'action')
        const block = annotation && sourceBlocks.find(item => item.id === annotation.block_id)
        if (!annotation || !block) continue
        const sourceText = block.text.slice(annotation.start, annotation.end)
        const actionStart = sourceText.indexOf(action.text)
        const boundary = actionStart < 0 ? -1 : annotation.start + actionStart + splitAt
        if (boundary <= annotation.start || boundary >= annotation.end) continue
        const rightAnnotationId = localId('annotation')
        annotations = annotations.map(item => item.id === annotation.id
          ? { ...item, end: boundary, origin: 'user', confidence: 1, accepted: true }
          : item)
        annotations.push({
          ...annotation,
          id: rightAnnotationId,
          start: boundary,
          origin: 'user',
          confidence: 1,
          accepted: true,
        })
        rightSourceAnnotationIds = rightSourceAnnotationIds.map(id => id === annotation.id ? rightAnnotationId : id)
        sourceBoundary = { blockId: annotation.block_id, index: boundary }
        break
      }

      const annotationById = new Map(annotations.map(item => [item.id, item]))
      const bindingBelongsToRight = (binding: BackendMethodBinding) => {
        const annotation = binding.annotation_id ? annotationById.get(binding.annotation_id) : undefined
        if (annotation && sourceBoundary && annotation.block_id === sourceBoundary.blockId) {
          return annotation.start >= sourceBoundary.index
        }
        const ingredient = data?.ingredients.find(item => item.lineage_id === binding.ingredient_lineage_id)
        const terms = (ingredient?.name.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [])
          .flatMap(term => term.endsWith('s') ? [term, term.slice(0, -1)] : [term])
          .filter(term => term.length > 2)
        const leftHasIngredient = terms.some(term => leftText.toLocaleLowerCase().includes(term))
        const rightHasIngredient = terms.some(term => rightText.toLocaleLowerCase().includes(term))
        return rightHasIngredient && !leftHasIngredient
      }

      const durationPattern = /\b\d+(?:[.,]\d+)?\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b/i
      const temperaturePattern = /(?:°|\b(?:oven|degrees?|celsius|fahrenheit)\b)/i
      const moveDuration = Boolean(action.duration_minutes != null && durationPattern.test(rightText) && !durationPattern.test(leftText))
      const moveTemperature = Boolean(action.temperature_value != null && temperaturePattern.test(rightText) && !temperaturePattern.test(leftText))
      const moveCue = Boolean(action.cue && rightText.toLocaleLowerCase().includes(action.cue.toLocaleLowerCase()) && !leftText.toLocaleLowerCase().includes(action.cue.toLocaleLowerCase()))
      const rightEquipment = action.equipment.filter(item => rightText.toLocaleLowerCase().includes(item.toLocaleLowerCase()))
      const leftEquipment = action.equipment.filter(item => !rightEquipment.includes(item) || leftText.toLocaleLowerCase().includes(item.toLocaleLowerCase()))
      const originalAction: BackendMethodAction = {
        ...action,
        text: leftText,
        source_annotation_ids: action.source_annotation_ids,
        duration_minutes: moveDuration ? undefined : action.duration_minutes,
        temperature_value: moveTemperature ? undefined : action.temperature_value,
        temperature_unit: moveTemperature ? undefined : action.temperature_unit,
        cue: moveCue ? undefined : action.cue,
        equipment: leftEquipment,
      }
      const newAction: BackendMethodAction = {
        ...action,
        id: newActionId,
        position: action.position + 1,
        text: rightText,
        source_annotation_ids: rightSourceAnnotationIds,
        duration_minutes: moveDuration ? action.duration_minutes : undefined,
        temperature_value: moveTemperature ? action.temperature_value : undefined,
        temperature_unit: moveTemperature ? action.temperature_unit : undefined,
        cue: moveCue ? action.cue : undefined,
        equipment: rightEquipment,
      }
      const actionIndex = current.actions.findIndex(item => item.id === action.id)
      const shiftedActions = current.actions.map(item => {
        if (item.id === action.id) return originalAction
        if (item.stage_id === action.stage_id && item.position > action.position) {
          return { ...item, position: item.position + 1 }
        }
        return item
      })
      shiftedActions.splice(actionIndex + 1, 0, newAction)

      return {
        ...current,
        annotations,
        actions: shiftedActions,
        ingredient_bindings: current.ingredient_bindings.map(binding => (
          binding.action_id === action.id && bindingBelongsToRight(binding)
            ? { ...binding, action_id: newActionId }
            : binding
        )),
        edges: [
          ...current.edges.map(edge => edge.from_action_id === action.id
            ? { ...edge, from_action_id: newActionId }
            : edge),
          {
            id: localId('edge'),
            from_action_id: action.id,
            to_action_id: newActionId,
            kind: 'sequence',
            confidence: 1,
          },
        ],
      }
    })
    setSelectedActions(new Set())
    setMessage('Step split into two editable steps.')
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
    const type = event.active.data.current?.type as 'ingredient' | 'action'
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
    if (activeType === 'ingredient') {
      const lineageId = activeId.replace('ingredient:', '')
      const overData = event.over?.data.current
      if (overData?.type === 'source-word') {
        linkIngredientToSourceRange(lineageId, {
          blockId: String(overData.blockId),
          start: Number(overData.start),
          end: Number(overData.end),
          text: String(overData.text),
        })
      } else if (overData?.type === 'action') {
        attachIngredient(lineageId, overId.replace('action:', ''))
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
      {methodQuery.error && !unavailable && <Notice tone="warning" title="Method unavailable">
        <span>{methodQuery.error instanceof Error ? methodQuery.error.message : 'The method could not be loaded.'}</span>
        {recoveryActionView}
      </Notice>}
      <Card className="method-empty-state">
        {recipe.data?.source_url && <Button disabled={extract.isPending} onClick={() => extract.mutate()}><Sparkles size={17}/>{extract.isPending ? 'Reading source…' : 'Create draft from source'}</Button>}
        <div className="method-empty-divider"><span>or</span></div>
        <label>Write or paste the cooking method<textarea rows={10} value={manualText} onChange={event => setManualText(event.target.value)} placeholder="Fry the onions until soft. Add the tomatoes…"/></label>
        <Button variant="secondary" disabled={!manualText.trim()} onClick={createManual}><PencilLine size={17}/>Build from this text</Button>
        {safeExternalUrl(recipe.data?.source_url) && <a className="source-link" href={safeExternalUrl(recipe.data?.source_url) ?? undefined} target="_blank" rel="noreferrer">Open original recipe <ExternalLink size={15}/></a>}
      </Card>
    </div>
  }

  const selectedIngredientId = selectedIngredients.size === 1 ? [...selectedIngredients][0] : undefined
  const draggedIngredientId = activeDrag?.type === 'ingredient' ? activeDrag.id.replace('ingredient:', '') : undefined
  const linkIngredientId = draggedIngredientId ?? selectedIngredientId
  const linkIngredientName = data.ingredients.find(item => item.lineage_id === linkIngredientId)?.name
  const unreviewed = Number(data.coverage.unreviewed ?? 0)
  const lowConfidence = method.annotations.filter(item => item.confidence < .65 && !item.accepted).length + method.ingredient_bindings.filter(item => item.confidence < .65 && !item.accepted).length
  const unresolvedClauses = unreviewedClauses(sourceBlocks, method.annotations)
  return <div className="page page--wide method-page">
    <PageHeader
      eyebrow={data.batch_context ? `Batch method · ${data.batch_context.servings} servings` : preview ? 'Method preview' : 'Cooking method'}
      title={data.title}
      description={data.publisher ? `From ${data.publisher}. Source wording is kept private and attributed.` : 'Your household cooking method.'}
      actions={<>
        <Link className="button button--ghost" to={batchId ? '/week' : '/recipes'}><ArrowLeft size={17}/>Back</Link>
        {safeExternalUrl(data.source_url) && <a className="button button--secondary" href={safeExternalUrl(data.source_url) ?? undefined} target="_blank" rel="noreferrer">Source <ExternalLink size={16}/></a>}
        {!preview && data.source_kind === 'publisher' && <Button variant="secondary" disabled={refreshPreview.isPending} onClick={() => refreshPreview.mutate()}><RefreshCw className={refreshPreview.isPending ? 'spin' : ''} size={16}/>{refreshPreview.isPending ? 'Checking…' : 'Check source'}</Button>}
        {!preview && !editing && data.method_status === 'needs_review' && <Button type="button" disabled={savePending || Boolean(conflictLatest) || Boolean(sourceEditBlockId)} title={sourceEditBlockId ? 'Finish editing the method wording first.' : undefined} onClick={() => void saveMethod()}><Save size={16}/>{savePending ? 'Saving…' : 'Save'}</Button>}
        {!preview && <Button variant="secondary" disabled={Boolean(sourceEditBlockId)} title={sourceEditBlockId ? 'Finish editing the method wording first.' : undefined} onClick={() => setEditing(value => !value)}><PencilLine size={16}/>{editing ? 'Close editor' : 'Edit method'}</Button>}
      </>}
    />
    {servingError && <Notice tone="warning" title="Serving count not applied"><span>{servingError}</span>{recoveryActionView}</Notice>}
    {error && <Notice tone="warning" title="Method update failed">{error}</Notice>}
    {message && <Notice tone="success" title="Saved">{message}</Notice>}
    <div className="method-status" aria-live="polite"><Badge tone={data.method_status === 'reviewed' ? 'green' : 'warning'}>{data.method_status === 'reviewed' ? 'Reviewed' : 'Needs review'}</Badge></div>
    {data.method_status === 'needs_review' && <Notice tone="warning" title="Automatically generated draft">Save when you have finished reviewing. {unreviewed ? `${unreviewed} unaccounted clause${unreviewed === 1 ? '' : 's'} will remain highlighted as a warning.` : 'The highlighted suggestions are optional to accept.'}</Notice>}
    {data.batch_context && <Card className="method-batch-banner"><Flame/><div><strong>Cook the whole batch: {data.batch_context.servings} servings</strong><span>{data.batch_context.occurrences.map(item => `${item.date} ${item.meal_type}`).join(' · ')}</span></div></Card>}
    <div className="method-toolbar">
      {!data.batch_context && data.scaling_available && <form className="method-serving-control" onSubmit={event => { event.preventDefault(); commitServings() }}>
        <label htmlFor="method-servings">Servings</label>
        <input ref={servingsInputRef} id="method-servings" name="servings" type="number" min=".25" step=".25" value={servingValue} onChange={event => { setServingsDraft(event.target.value); setError(''); setServingError('') }} onBlur={commitServings} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); commitServings() } }} />
        {servingDraftChanged && <Button type="submit" variant="secondary" disabled={servingPending}>{servingPending ? 'Applying…' : 'Apply'}</Button>}
      </form>}
      <button className="method-help-button" type="button" onClick={() => setTutorialStep(0)}><CircleHelp size={17}/>How to edit</button>
    </div>

    {preview && <Card className="method-preview-save"><div><span className="eyebrow">Keep this recipe</span><strong>Save ingredients and the written method together</strong></div><MealTypePicker value={mealTypes} onChange={setMealTypes}/><Button disabled={!mealTypes.length || savePreview.isPending} onClick={() => savePreview.mutate()}><Save size={16}/>{savePreview.isPending ? 'Saving…' : 'Save recipe'}</Button></Card>}

    {editing ? <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={handleDragStart} onDragMove={handleDragMove} onDragCancel={() => { setActiveDrag(null); setBreakingAction(null); setBreakingStrength(0) }} onDragEnd={handleDragEnd}>
      <div className="method-editor-shell">
        <aside className="method-editor-guide">
          <p className="eyebrow">Review path</p>
          <ol><li className="done"><Check/>Ingredient mentions</li><li className={method.annotations.length ? 'done' : ''}><Check/>Semantic spans</li><li className={data.method_status === 'reviewed' ? 'done' : ''}><Check/>Review and save</li></ol>
          <div className="method-editor-selection"><strong>{selectedIngredients.size} ingredient{selectedIngredients.size === 1 ? '' : 's'} selected</strong></div>
          {lowConfidence > 0 && <Button variant="ghost" onClick={acceptSuggestions}><Check size={15}/>Accept {lowConfidence} suggestions</Button>}
        </aside>
        <section className="method-source-editor">
          <div className="method-section-heading"><div><span className="eyebrow">1 · Mark up the source</span><h2>Original written method</h2></div><Badge>{data.source_kind === 'publisher' ? 'Read-only source' : 'Editable source'}</Badge></div>
          <div className="method-ingredient-linker">
            <div><strong>Link amounts to exact wording</strong><span>Select an ingredient, then tap a word, or drag the ingredient onto it. This works with a mouse, touch, or keyboard.</span></div>
            <div className="method-ingredient-palette">{data.ingredients.map(ingredient => <DraggableIngredient key={ingredient.lineage_id} ingredient={ingredient} selected={selectedIngredients.has(ingredient.lineage_id)} onSelect={() => setSelectedIngredients(current => { const next = new Set(current); next.has(ingredient.lineage_id) ? next.delete(ingredient.lineage_id) : next.add(ingredient.lineage_id); return next })}/>)}</div>
          </div>
          {unreviewed > 0 && <div className="method-unreviewed" role="region" aria-labelledby="method-unreviewed-title">
            <div className="method-unreviewed__heading"><strong id="method-unreviewed-title">{unreviewed} unaccounted clause{unreviewed === 1 ? '' : 's'}</strong><span>Check the highlighted wording when useful. This warning does not block saving the reviewed method.</span></div>
            {unresolvedClauses.length > 0 && <ol>{unresolvedClauses.map(({ annotation, text }, index) => <li key={annotation.id}><button type="button" onClick={() => {
              const target = document.getElementById(`unreviewed-clause-${annotation.id}`)
              target?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
              target?.focus({ preventScroll: true })
            }} aria-label={`Locate unaccounted clause ${index + 1}: ${text}`}><span aria-hidden="true">{index + 1}</span><strong>{text}</strong><Link2 size={14} aria-hidden="true"/></button></li>)}</ol>}
          </div>}
          {sourceBlocks.map((block, index) => <article className="method-source-block" key={block.id}>
            {block.heading && <h3>{block.heading}</h3>}
            {data.source_kind === 'publisher' || sourceEditBlockId !== block.id
              ? <>
                <p ref={node => { sourceRefs.current[block.id] = node }} onPointerUp={() => captureSelection(block)} onKeyUp={() => captureSelection(block)}>{annotatedSource(block, method.annotations, linkIngredientId, linkIngredientName, range => linkIngredientToSourceRange(linkIngredientId!, range))}</p>
                {data.source_kind !== 'publisher' && <Button type="button" variant="ghost" className="method-source-edit-button" onClick={() => { setSourceEditBlockId(block.id); setSelection(null); setError('') }}><PencilLine size={15}/>Edit wording</Button>}
              </>
              : <div className="method-source-text-edit">
                <textarea value={block.text} rows={5} autoFocus onChange={event => { const text = event.target.value; setSourceBlocks(items => items.map((item, itemIndex) => itemIndex === index ? { ...item, text } : item)); setSelection(null); setDirty(true) }} />
                <div><small>Changing the wording rebuilds this block’s step suggestions. Re-link ingredients after saving.</small><Button type="button" variant="secondary" onClick={() => finishSourceTextEdit(block.id)}>Done editing wording</Button></div>
              </div>}
            <div className="method-source-tags">{method.annotations.filter(item => item.block_id === block.id).map(annotation => <button type="button" className={`semantic-chip semantic-chip--${annotation.kind}`} key={annotation.id} title="Remove this label" onClick={() => removeAnnotation(annotation.id)}><span>{annotation.kind}: {block.text.slice(annotation.start, annotation.end)}</span><X size={12}/></button>)}</div>
          </article>)}
          {selection && <div className="semantic-toolbar" role="toolbar" aria-label="Mark selected recipe text"><div><strong>“{selection.text.slice(0, 56)}{selection.text.length > 56 ? '…' : ''}”</strong><span>What does this text mean?</span></div>{semanticTools.map(tool => { const Icon = tool.icon; return <button type="button" key={tool.kind} onClick={() => tagSelection(tool.kind)}><Icon size={15}/>{tool.label}</button> })}<button type="button" onClick={() => { updateDocument(current => ({ ...current, omissions: [...current.omissions, { id: localId('omission'), block_id: selection.blockId, start: selection.start, end: selection.end, reason: 'Omitted from concise summary', accepted: true }] })); setSelection(null) }}><Trash2 size={15}/>Omit</button>{annotationIngredient && <select aria-label="Ingredient for selected text" value={annotationIngredient} onChange={event => setAnnotationIngredient(event.target.value)}>{data.ingredients.map(item => <option key={item.lineage_id} value={item.lineage_id}>{item.name}</option>)}</select>}</div>}
        </section>
        <section className="method-editor-save"><label>Household notes<textarea rows={3} value={notes} onChange={event => { setNotes(event.target.value); setDirty(true) }} placeholder="Add adaptations or reminders without changing the publisher wording."/></label><div><Button type="button" disabled={savePending || Boolean(conflictLatest) || Boolean(sourceEditBlockId)} title={sourceEditBlockId ? 'Finish editing the method wording first.' : undefined} onClick={() => void saveMethod()}><Save size={16}/>{savePending ? 'Saving…' : 'Save'}</Button></div></section>
      </div>
      <DragOverlay>{activeDrag && <div className={`method-drag-overlay method-drag-overlay--${activeDrag.type}`}><GripVertical size={15}/>{activeDrag.label}</div>}</DragOverlay>
    </DndContext> : <WrittenMethod data={data}/>}

    {conflictLatest && <div className="modal-backdrop" role="presentation"><Card className="method-conflict" role="dialog" aria-modal="true" aria-labelledby="method-conflict-title"><AlertTriangle/><div><p className="eyebrow">Version conflict</p><h2 id="method-conflict-title">Someone saved this method first</h2><p>Your local draft is safe. The latest version has {conflictLatest.method.actions.length} actions; yours has {method.actions.length}.</p><div className="button-row"><Button variant="secondary" onClick={() => { setData(conflictLatest); setMethod(structuredClone(conflictLatest.method)); setSourceBlocks(structuredClone(conflictLatest.source_blocks)); setDirty(false); setConflictLatest(null) }}>Load latest</Button><Button onClick={() => { setData(current => current ? { ...current, recipe_version: conflictLatest.recipe_version } : current); setConflictLatest(null); setMessage('Your draft is ready to reapply over the latest version.') }}>Reapply my draft</Button></div></div></Card></div>}
    {refreshCandidate && <div className="modal-backdrop" role="presentation"><Card className="method-refresh-dialog" role="dialog" aria-modal="true" aria-labelledby="method-refresh-title"><RefreshCw/><div><p className="eyebrow">Source comparison</p><h2 id="method-refresh-title">{refreshCandidate.refresh_diff?.changed ? 'The publisher method changed' : 'The publisher method is unchanged'}</h2><p>{refreshCandidate.refresh_diff?.changed ? `The saved method has ${refreshCandidate.refresh_diff.old_block_count ?? 0} source blocks; the current page has ${refreshCandidate.refresh_diff.new_block_count ?? 0}. Applying creates a new immutable recipe version and keeps your history intact.` : 'Your saved source checksum matches the current page. No update is needed.'}</p><div className="button-row"><Button variant="ghost" onClick={() => setRefreshCandidate(null)}>Close</Button>{refreshCandidate.refresh_diff?.changed && <Button disabled={applyRefresh.isPending} onClick={() => applyRefresh.mutate()}><RefreshCw className={applyRefresh.isPending ? 'spin' : ''} size={16}/>{applyRefresh.isPending ? 'Applying…' : 'Apply as new draft'}</Button>}</div></div></Card></div>}
    {tutorialStep != null && <Tutorial step={tutorialStep} setStep={setTutorialStep} dismiss={dismissTutorial}/>}
  </div>
}

function WrittenMethod({ data }: { data: BackendMethodView }) {
  return <div className="written-method-layout"><aside className="method-ingredients-panel"><div className="method-panel-heading"><span>For {data.requested_servings ?? data.base_servings ?? 'the recipe'}</span><Badge>{data.ingredients.length} ingredients</Badge></div><ol>{data.ingredients.map(item => <li key={item.lineage_id}><span>{item.quantity_text} {item.unit}</span><strong>{item.name}</strong></li>)}</ol></aside><main className="written-method"><div className="written-method-key"><span><i className="semantic-dot semantic-dot--ingredient"/>Linked ingredient</span><span>Quantities update with the batch</span></div>{data.rendered_blocks.map((block, index) => <article key={block.id}><span className="written-step-number">{String(index + 1).padStart(2,'0')}</span><div>{block.heading && <h2>{block.heading}</h2>}<p>{block.segments.map((segment, segmentIndex) => segment.kind === 'ingredient' ? <mark className="written-ingredient" key={segmentIndex}>{segment.text}{segment.quantity_label && <small>{segment.quantity_label}</small>}</mark> : <span key={segmentIndex}>{segment.text}</span>)}</p></div></article>)}{data.household_notes && <Card className="method-household-notes"><strong>Household notes</strong><p>{data.household_notes}</p></Card>}</main></div>
}

function DraggableIngredient({ ingredient, selected, onSelect }: { ingredient: BackendMethodIngredient; selected: boolean; onSelect: () => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `ingredient:${ingredient.lineage_id}`, data: { type: 'ingredient', label: ingredient.name } })
  return <button ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform) }} className={`method-ingredient-chip${selected ? ' selected' : ''}${isDragging ? ' is-dragging' : ''}`} type="button" onClick={onSelect} {...listeners} {...attributes}><GripVertical size={13}/><span>{ingredient.quantity_text} {ingredient.unit}</span><strong>{ingredient.name}</strong></button>
}

function DroppableStage({ stage, actions, method, ingredients, selectedActions, setSelectedActions, updateDocument, onSplit, breakingAction, breakingStrength, justGrouped }: {
  stage: BackendMethodStage
  actions: BackendMethodAction[]
  method: BackendMethodDocument
  ingredients: BackendMethodIngredient[]
  selectedActions: Set<string>
  setSelectedActions: Dispatch<SetStateAction<Set<string>>>
  updateDocument: (updater: (current: BackendMethodDocument) => BackendMethodDocument) => void
  onSplit: (actionId: string, splitAt: number) => void
  breakingAction: string | null
  breakingStrength: number
  justGrouped: string | null
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `stage:${stage.id}`, data: { type: 'stage' } })
  return <section ref={setNodeRef} className={`method-canvas-stage${isOver ? ' is-over' : ''}`}><header><input aria-label="Stage name" value={stage.title} onChange={event => updateDocument(current => ({ ...current, stages: current.stages.map(item => item.id === stage.id ? { ...item, title: event.target.value } : item) }))}/><Badge>{actions.length} steps</Badge></header><SortableContext items={actions.map(action => `action:${action.id}`)} strategy={verticalListSortingStrategy}>{actions.map(action => <SortableAction key={action.id} action={action} method={method} ingredients={ingredients} selected={selectedActions.has(action.id)} onSelect={() => setSelectedActions(current => { const next = new Set(current); next.has(action.id) ? next.delete(action.id) : next.add(action.id); return next })} updateDocument={updateDocument} onSplit={onSplit} breaking={breakingAction === `action:${action.id}`} breakingStrength={breakingStrength} grouped={justGrouped === action.id}/>)}</SortableContext>{!actions.length && <div className="method-stage-drop-hint">Drop actions here to build a parallel lane</div>}</section>
}

function SortableAction({ action, method, ingredients, selected, onSelect, updateDocument, onSplit, breaking, breakingStrength, grouped }: {
  action: BackendMethodAction
  method: BackendMethodDocument
  ingredients: BackendMethodIngredient[]
  selected: boolean
  onSelect: () => void
  updateDocument: (updater: (current: BackendMethodDocument) => BackendMethodDocument) => void
  onSplit: (actionId: string, splitAt: number) => void
  breaking: boolean
  breakingStrength: number
  grouped: boolean
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging, isOver } = useSortable({ id: `action:${action.id}`, data: { type: 'action', label: action.text } })
  const [splitAt, setSplitAt] = useState<number | null>(null)
  const ingredientMap = new Map(ingredients.map(item => [item.lineage_id, item]))
  const bindings = method.ingredient_bindings.filter(item => item.action_id === action.id)
  const breakClass = breaking ? (breakingStrength > .72 ? ' is-breaking is-breaking--hard' : breakingStrength > .32 ? ' is-breaking is-breaking--medium' : ' is-breaking') : ''
  const canSplit = validSplitPosition(action.text, splitAt)
  const splitHelpId = `split-help-${action.id}`
  return <article ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={`method-action-card${selected ? ' selected' : ''}${isDragging ? ' is-dragging' : ''}${isOver ? ' is-over' : ''}${breakClass}${grouped ? ' just-grouped' : ''}`} onClick={onSelect}>
    <button type="button" className="method-drag-handle" aria-label={`Move ${action.text}`} {...listeners} {...attributes}><GripVertical/></button>
    <div className="method-action-inputs">{bindings.map(binding => { const ingredient = ingredientMap.get(binding.ingredient_lineage_id); return ingredient && <span key={binding.id}>{ingredient.name}<button type="button" aria-label={`Remove ${ingredient.name} from ${action.text}`} onClick={event => { event.stopPropagation(); updateDocument(current => ({ ...current, ingredient_bindings: current.ingredient_bindings.filter(item => item.id !== binding.id) })) }}><X/></button></span> })}</div>
    <textarea
      aria-label="Action text"
      rows={2}
      value={action.text}
      onClick={event => { event.stopPropagation(); setSplitAt(event.currentTarget.selectionStart) }}
      onSelect={event => setSplitAt(event.currentTarget.selectionStart)}
      onKeyUp={event => setSplitAt(event.currentTarget.selectionStart)}
      onChange={event => {
        const text = event.currentTarget.value
        setSplitAt(event.currentTarget.selectionStart)
        updateDocument(current => ({ ...current, actions: current.actions.map(item => item.id === action.id ? { ...item, text } : item) }))
      }}
    />
    <div className="method-action-edit-tools" onClick={event => event.stopPropagation()}>
      <span id={splitHelpId}>{canSplit ? 'Ready to create the next step here.' : 'Place the text cursor between words to split this step.'}</span>
      <button type="button" disabled={!canSplit} aria-describedby={splitHelpId} onClick={() => {
        if (splitAt != null) onSplit(action.id, splitAt)
        setSplitAt(null)
      }}><Split size={14} aria-hidden="true"/>Split step at cursor</button>
    </div>
    <div className="method-action-properties">{action.duration_minutes != null && <span><Clock3/>{action.duration_minutes} min</span>}{action.temperature_value != null && <span><Thermometer/>{action.temperature_value}°{action.temperature_unit?.toUpperCase()}</span>}{action.cue && <span><Check/>{action.cue}</span>}</div>
  </article>
}

function Tutorial({ step, setStep, dismiss }: { step: number; setStep: (step: number | null) => void; dismiss: () => Promise<void> }) {
  const slides = [
    { icon: Tag, title: 'Link exact ingredient words', copy: 'Drag an ingredient onto the matching word. For keyboard or touch editing, select the ingredient first and then choose the word.' },
  ]
  const slide = slides[step]
  const Icon = slide.icon
  return <div className="method-tutorial-backdrop" role="presentation"><Card className="method-tutorial" role="dialog" aria-modal="true" aria-labelledby="method-tutorial-title"><button type="button" className="modal-close" aria-label="Dismiss tutorial" onClick={() => void dismiss()}><X/></button><div className="method-tutorial-visual"><Icon/></div><p className="eyebrow">Quick tour · {step + 1}/{slides.length}</p><h2 id="method-tutorial-title">{slide.title}</h2><p>{slide.copy}</p><div className="method-tutorial-dots">{slides.map((_, index) => <i className={index === step ? 'active' : ''} key={index}/>)}</div><div className="button-row"><Button variant="ghost" onClick={() => void dismiss()}>Dismiss</Button>{step < slides.length - 1 ? <Button onClick={() => setStep(step + 1)}>Next</Button> : <Button onClick={() => void dismiss()}><Check size={16}/>Start editing</Button>}</div></Card></div>
}
