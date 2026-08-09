import { describe, expect, it } from 'vitest'

import fixture from './fixtures/recipe_flow_layout.json'
import { createFlowTableLayout, type FlowTableLayout } from './recipeFlowLayout'
import type { BackendMethodDocument, BackendMethodTableDocument } from '../api/client'

describe('recipe Flow table layout contract', () => {
  it('matches the shared branch, merge, span, and lane fixture', () => {
    const layout = createFlowTableLayout(
      fixture.method as unknown as BackendMethodDocument,
      fixture.table as unknown as BackendMethodTableDocument,
    )
    expect(layout).toEqual(fixture.expected as FlowTableLayout)
  })
})
