import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { BackendMethodDocument, BackendMethodTableDocument, BackendMethodView } from '../api/client'
import { RecipeFlowTable } from './RecipeFlowTable'

const method: BackendMethodDocument = {
  schema_version: 1,
  annotations: [{ id: 'annotation-1', block_id: 'block-1', start: 0, end: 100, kind: 'action', origin: 'user', confidence: 1, accepted: true }],
  omissions: [],
  stages: [{ id: 'stage-1', title: 'Cook', position: 0 }],
  actions: [{ id: 'action-1', stage_id: 'stage-1', position: 0, text: 'Simmer the lentils', source_annotation_ids: ['annotation-1'], duration_minutes: 20, duration_text: '20 minutes', equipment: ['pan'], confidence: 1 }],
  ingredient_bindings: [{ id: 'binding-1', action_id: 'action-1', ingredient_lineage_id: 'lineage-1', role: 'input', portion_mode: 'all', confidence: 1, accepted: true }],
  edges: [],
}

const table: BackendMethodTableDocument = {
  schema_version: 1,
  labels: [{ action_id: 'action-1', text: 'simmer lentils · 20 min', origin: 'user', confidence: 1, accepted: true }],
  row_order: ['binding-1'],
  column_hints: [],
  setup_action_ids: [],
  terminal_action_ids: ['action-1'],
  omissions: [],
}

const data: BackendMethodView = {
  title: 'Lentils',
  method_status: 'needs_review',
  source_kind: 'custom',
  source_blocks: [{ id: 'block-1', position: 0, text: 'Simmer the lentils for 20 minutes.' }],
  method,
  coverage: { total_clauses: 1, represented: 1, omitted: 0, unreviewed: 0 },
  ingredients: [{ id: 'ingredient-1', lineage_id: 'lineage-1', name: 'lentils', quantity: 2, quantity_text: '2', unit: 'cups', display: '2 cups lentils', optional: false }],
  rendered_blocks: [],
  scaling_available: true,
  table: {
    status: 'needs_review',
    confidence: 1,
    coverage: { total_actions: 1, represented_actions: 1, total_included_ingredient_lineages: 1, represented_ingredient_lineages: 1, ingredient_use_rows: 1, explicitly_omitted_ingredients: 0, explicitly_omitted_actions: 0, unplaced_ingredients: 0, disconnected_components: 1, low_confidence_labels: 0, low_confidence_bindings: 0, low_confidence_edges: 0, blocking_warnings: 0, non_blocking_warnings: 0 },
    document: table,
    rendered_ingredient_uses: [{ binding_id: 'binding-1', ingredient_lineage_id: 'lineage-1', target_action_id: 'action-1', name: 'lentils', quantity: 2, quantity_text: '2', unit: 'cups', portion_mode: 'all', optional: false, display: '2 cups lentils' }],
    warnings: [],
  },
}

describe('RecipeFlowTable', () => {
  it('renders read-only rows, operation details, and accessible linearisation without a DnD provider', () => {
    render(<RecipeFlowTable data={data} method={method} table={table}/>)

    expect(screen.getByRole('grid')).toBeInTheDocument()
    expect(screen.getByLabelText('Swipe through cooking operations')).toBeInTheDocument()
    expect(screen.getByText('2 cups lentils')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /simmer lentils/ })).toBeInTheDocument()
    expect(screen.getByText(/Step 1, simmer lentils/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /simmer lentils/ }))
    expect(screen.getByRole('complementary', { name: 'Details for simmer lentils · 20 min' })).toHaveTextContent('Simmer the lentils for 20 minutes.')
  })
})
