import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders recipe discovery with clear nutrition labels', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    expect(screen.getByRole('heading', { name: /find something delicious/i })).toBeInTheDocument()
    expect(screen.getAllByText(/nutrition from good food · per serving/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/nutrition from allrecipes · per serving/i)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /save recipe/i }).length).toBeGreaterThan(0)
  })

  it('opens website filters and lets a source be disabled', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    await user.click(screen.getByRole('button', { name: /recipe filters/i }))
    const goodFood = screen.getByRole('checkbox', { name: /good food/i })
    expect(screen.getByRole('checkbox', { name: /allrecipes/i })).toBeChecked()
    expect(screen.queryByRole('checkbox', { name: /great british chefs/i })).not.toBeInTheDocument()
    expect(goodFood).toBeChecked()
    await user.click(goodFood)
    expect(goodFood).not.toBeChecked()
  })

  it('keeps discovery and saved recipes in separate views', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('radio', { name: 'Discover' })).toBeChecked()
    expect(screen.getByRole('heading', { name: 'Berry overnight oats' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Wild mushroom risotto' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'My recipes' }))

    expect(screen.getByRole('heading', { name: 'Wild mushroom risotto' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Harissa chicken with chickpeas' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Edit recipe' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('link', { name: 'Edit meal types' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Berry overnight oats' })).not.toBeInTheDocument()
  })

  it('signs out from the dark theme', async () => {
    const user = userEvent.setup()
    localStorage.setItem('slop-theme', 'dark')
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/week']}><App/></MemoryRouter></QueryClientProvider>)

    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(screen.getByRole('heading', { name: 'Sign in to your household' })).toBeInTheDocument()
  })

  it('explains that settings need a live household in demo mode', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/settings/targets']}><App/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByText('Settings need a live household')).toBeInTheDocument()
    expect(screen.getByText(/theme changes remain available from the app menu/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Add person' })).not.toBeInTheDocument()
  })

  it('filters by categories without a text query and enforces the three-category limit', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    await user.click(screen.getByRole('button', { name: /recipe filters/i }))

    await user.click(screen.getByRole('checkbox', { name: 'Healthy' }))
    expect(screen.queryByRole('heading', { name: 'Wild mushroom risotto' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Berry overnight oats' })).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Soups' }))
    await user.click(screen.getByRole('checkbox', { name: 'Salads' }))
    expect(screen.getByText('3/3')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Pasta' })).toBeDisabled()
  })

  it('switches selected categories between matching any and matching all', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)
    await user.click(screen.getByRole('button', { name: /recipe filters/i }))
    await user.click(screen.getByRole('checkbox', { name: 'Healthy' }))
    await user.click(screen.getByRole('checkbox', { name: 'Dinner / Main dishes' }))

    expect(screen.getByRole('heading', { name: 'Berry overnight oats' })).toBeInTheDocument()
    const matchMode = screen.getByRole('switch', { name: 'Require all selected categories' })
    expect(matchMode).not.toBeChecked()
    await user.click(matchMode)

    expect(matchMode).toBeChecked()
    expect(screen.queryByRole('heading', { name: 'Berry overnight oats' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Fragrant green vegetable curry' })).toBeInTheDocument()
  })

  it('parks food matching in the import review', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/imports/demo/review']}><App/></MemoryRouter></QueryClientProvider>)
    expect(screen.getByRole('heading', { name: /harissa chicken with chickpeas/i })).toBeInTheDocument()
    expect(screen.getAllByText(/nutrition from good food/i).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Original recipe' })).not.toBeInTheDocument()
    expect(screen.queryByText(/food-data match|match foods|fallback calculation/i)).not.toBeInTheDocument()
  })

  it('keeps demo import servings connected to the review summary', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/imports/demo/review']}><App/></MemoryRouter></QueryClientProvider>)

    const servings = screen.getByRole('spinbutton', { name: 'Confirmed servings' })
    await user.clear(servings)
    await user.type(servings, '6')

    expect(servings).toHaveValue(6)
    expect(screen.getByText(/6 servings confirmed/i)).toBeInTheDocument()
  })

  it('previews recipe-specific serving increments while reviewing', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/imports/demo/review']}><App/></MemoryRouter></QueryClientProvider>)

    await user.type(screen.getByRole('spinbutton', { name: 'Minimum planned servings' }), '0.75')
    await user.type(screen.getByRole('spinbutton', { name: 'Serving increment' }), '0.5')

    expect(screen.getByText(/allows 0.75, 1.25, 1.75 servings/i)).toBeInTheDocument()
  })

  it('offers recipe deletion from the edit screen and confirms before leaving', async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes/demo/review']}><App/></MemoryRouter></QueryClientProvider>)

    await user.click(screen.getByRole('button', { name: 'Delete recipe' }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Existing meal plans keep their history.'))
    expect(screen.getByRole('heading', { name: /find something delicious/i })).toBeInTheDocument()
  })

  it('asks for meal types before finishing a searched recipe save', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)

    await user.click(screen.getAllByRole('button', { name: /save recipe/i })[0])
    const dialog = screen.getByRole('dialog', { name: /where should/i })
    const finish = screen.getByRole('button', { name: /finish saving/i })
    expect(dialog).toBeInTheDocument()
    expect(finish).toBeDisabled()

    await user.click(screen.getByText('Select meal types'))
    await user.click(screen.getByRole('checkbox', { name: 'Lunch' }))
    await user.click(finish)

    expect(await screen.findByText(/was saved for lunch/i)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /search recipes/i })).toBeInTheDocument()
  })

  it('reviews a problematic discovery import in a drawer without losing search context', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes']}><App/></MemoryRouter></QueryClientProvider>)

    const search = screen.getByRole('textbox', { name: /search recipes/i })
    await user.type(search, 'green')
    await user.click(screen.getByRole('button', { name: /recipe filters/i }))
    await user.click(screen.getByRole('checkbox', { name: 'Healthy' }))
    const recipeCard = screen.getByRole('heading', { name: 'Fragrant green vegetable curry' }).closest('.recipe-card')
    expect(recipeCard).not.toBeNull()
    const saveRecipe = within(recipeCard as HTMLElement).getByRole('button', { name: 'Save recipe' })
    await user.click(saveRecipe)
    await user.click(screen.getByText('Select meal types'))
    await user.click(screen.getByRole('checkbox', { name: 'Dinner' }))
    await user.click(screen.getByRole('button', { name: 'Finish saving' }))

    const drawer = await screen.findByRole('dialog', { name: 'Review imported recipe' })
    expect(within(drawer).getByRole('heading', { name: 'Fragrant green vegetable curry' })).toBeInTheDocument()
    expect(search).toHaveValue('green')
    expect(screen.getByRole('checkbox', { name: 'Healthy' })).toBeChecked()

    await user.click(within(drawer).getByRole('button', { name: 'Save recipe' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Review imported recipe' })).not.toBeInTheDocument())
    expect(search).toHaveValue('green')
    expect(screen.getByRole('checkbox', { name: 'Healthy' })).toBeChecked()
    await waitFor(() => expect(saveRecipe).toHaveFocus())
  })

  it('warns until a custom recipe has a meal type', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes/new']}><App/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByText(/not used for meal planning yet/i)).toBeInTheDocument()
    await user.click(screen.getByText('Select meal types'))
    await user.click(screen.getByRole('checkbox', { name: 'Lunch' }))

    expect(screen.queryByText(/not used for meal planning yet/i)).not.toBeInTheDocument()
    expect(screen.getByText('1 selected')).toBeInTheDocument()
  })

  it('opens the ingredient search page with scan and manual fallbacks', () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/ingredients']}><App/></MemoryRouter></QueryClientProvider>)

    expect(screen.getByRole('heading', { name: /find it once/i })).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/barcode number/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add manually/i })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: /general usda/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /packaged open food facts/i })).toBeChecked()
    expect(screen.getByRole('button', { name: /^search$/i })).toBeInTheDocument()
    expect(screen.getByText(/photo and number lookup still work/i)).toBeInTheDocument()
  })

  it('integrates nutrition search and barcode scanning while building a custom recipe', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/recipes/new']}><App/></MemoryRouter></QueryClientProvider>)

    await user.type(screen.getByRole('textbox', { name: /ingredient as written/i }), '200g yoghurt')

    await user.click(screen.getByRole('button', { name: /find nutrition/i }))
    expect(screen.getByRole('checkbox', { name: /general usda/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /packaged open food facts/i })).toBeChecked()
    expect(screen.getByRole('button', { name: /^search$/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /scan barcode/i }))
    expect(screen.getByRole('textbox', { name: /barcode number for recipe ingredient/i })).toBeInTheDocument()
    expect(screen.getByText(/photo and number lookup still work/i)).toBeInTheDocument()
    expect(screen.getByText(/0 of 1 ingredients matched/i)).toBeInTheDocument()
  })
})
