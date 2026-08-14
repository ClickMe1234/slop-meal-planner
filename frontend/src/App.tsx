import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes, useLocation, type Location } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { useTheme } from './lib/theme'
import { ChangePasswordPage, LoginPage, OnboardingPage, SetupPage } from './pages/AuthPages'
import { api, isDemoMode } from './api/client'
import { Loading } from './components/ui'
import { CustomRecipePage, ImportReviewDrawer, ImportReviewPage, RecipeImportPage } from './pages/ImportPages'
import { PantryPage } from './pages/PantryPage'
import { PlanPage } from './pages/PlanPage'
import { PlanEditPage } from './pages/PlanEditPage'
import { PlanRecipePickerPage } from './pages/PlanRecipePickerPage'
import { RecipesPage } from './pages/RecipesPage'
import { ShoppingPage } from './pages/ShoppingPage'
import { ShoppingIngredientChangePage, ShoppingItemDetailPage } from './pages/ShoppingIngredientPages'
import { AppearanceSettings, DataSettings, HouseholdSettings, PreferenceSettings, SystemSettings, TargetSettings } from './pages/SettingsPage'
import { WeekPage } from './pages/WeekPage'
import { IngredientsPage } from './pages/IngredientsPage'
import { MethodPage, MethodPreviewPage } from './pages/MethodPage'

export default function App() {
  const { theme, setTheme } = useTheme()
  const location = useLocation()
  const backgroundLocation = (location.state as { backgroundLocation?: Location } | null)?.backgroundLocation
  return <>
    <Routes location={backgroundLocation ?? location}>
    <Route path="/login" element={<LoginPage/>}/>
    <Route path="/setup" element={<SetupPage/>}/>
    <Route path="/change-password" element={<ChangePasswordPage/>}/>
    <Route path="/onboarding" element={<OnboardingPage/>}/>
    <Route element={<ProtectedShell theme={theme} setTheme={setTheme}/> }>
      <Route path="/week" element={<WeekPage/>}/>
      <Route path="/plan" element={<PlanPage/>}/>
      <Route path="/plan/:planId/edit" element={<PlanEditPage/>}/>
      <Route path="/plan/:planId/occurrences/:occurrenceId/recipes" element={<PlanRecipePickerPage/>}/>
      <Route path="/plan/:planId/batches/:batchId/sides/:componentSlot/recipes" element={<PlanRecipePickerPage/>}/>
      <Route path="/recipes" element={<RecipesPage/>}/>
      <Route path="/recipes/method-preview" element={<MethodPreviewPage/>}/>
      <Route path="/ingredients" element={<IngredientsPage/>}/>
      <Route path="/recipes/new" element={<CustomRecipePage/>}/>
      <Route path="/recipes/import" element={<RecipeImportPage/>}/>
      <Route path="/imports/:jobId/review" element={<ImportReviewPage/>}/>
      <Route path="/recipes/:recipeId/review" element={<ImportReviewPage/>}/>
      <Route path="/recipes/:recipeId/method" element={<MethodPage/>}/>
      <Route path="/pantry" element={<PantryPage/>}/>
      <Route path="/shopping" element={<ShoppingPage/>}/>
      <Route path="/shopping/:listId/items/:itemId" element={<ShoppingItemDetailPage/>}/>
      <Route path="/shopping/:listId/ingredient-change" element={<ShoppingIngredientChangePage/>}/>
      <Route path="/settings" element={<HouseholdSettings/>}/>
      <Route path="/settings/targets" element={<TargetSettings/>}/>
      <Route path="/settings/preferences" element={<PreferenceSettings/>}/>
      <Route path="/settings/appearance" element={<AppearanceSettings theme={theme} setTheme={setTheme}/>}/>
      <Route path="/settings/data" element={<DataSettings/>}/>
      <Route path="/settings/system" element={<SystemSettings/>}/>
    </Route>
    <Route path="*" element={<Navigate to="/week" replace/>}/>
    </Routes>
    {backgroundLocation && <Routes>
      <Route path="/imports/:jobId/review" element={<ImportReviewDrawer/>}/>
    </Routes>}
  </>
}

function ProtectedShell({ theme, setTheme }: { theme: ReturnType<typeof useTheme>['theme']; setTheme: ReturnType<typeof useTheme>['setTheme'] }) {
  const session = useQuery({ queryKey: ['session'], queryFn: api.me, enabled: !isDemoMode, retry: false })
  if (!isDemoMode && session.isLoading) return <div className="page"><Loading label="Opening your household…"/></div>
  if (!isDemoMode && session.isError) return <Navigate to="/login" replace/>
  if (!isDemoMode && session.data?.must_change_password) return <Navigate to="/change-password" replace/>
  return <AppShell theme={theme} setTheme={setTheme}/>
}
