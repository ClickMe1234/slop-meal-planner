import type { DayPlan, PantryItem, Recipe, ShoppingItem } from '../types'

export const demoRecipes: Recipe[] = [
  {
    id: 'harissa-chicken',
    title: 'Harissa chicken with chickpeas',
    source: 'Good Food',
    sourceUrl: 'https://www.bbcgoodfood.com/',
    imageUrl: 'https://images.unsplash.com/photo-1604908176997-125f25cc6f3d?auto=format&fit=crop&w=900&q=75',
    yield: 4,
    state: 'ready',
    nutrition: { calories: 524, protein: 48, carbs: 39, fat: 18, basis: 'per_serving' },
    nutritionSource: 'publisher',
    nutritionSourceName: 'Good Food',
    mealKinds: ['Lunch', 'Dinner'],
    ingredients: ['600g chicken thighs', '2 × 400g tins chickpeas', '2 tbsp harissa', '1 lemon']
  },
  {
    id: 'mushroom-risotto',
    title: 'Wild mushroom risotto',
    source: 'Saved recipe',
    sourceUrl: '#',
    imageUrl: 'https://images.unsplash.com/photo-1476124369491-e7addf5db371?auto=format&fit=crop&w=900&q=75',
    yield: 4,
    state: 'no_nutrition',
    mealKinds: ['Dinner']
  },
  {
    id: 'overnight-oats',
    title: 'Berry overnight oats',
    source: 'Allrecipes',
    sourceUrl: 'https://www.allrecipes.com/',
    imageUrl: 'https://images.unsplash.com/photo-1517673132405-a56a62b18caf?auto=format&fit=crop&w=900&q=75',
    yield: 1,
    state: 'source_estimate',
    publisherNutrition: { calories: 386, protein: 17, carbs: 56, fat: 10, basis: 'per_serving' },
    nutritionSourceName: 'Allrecipes',
    mealKinds: ['Breakfast']
  },
  {
    id: 'green-curry',
    title: 'Fragrant green vegetable curry',
    source: 'Good Food',
    sourceUrl: 'https://www.bbcgoodfood.com/',
    imageUrl: 'https://images.unsplash.com/photo-1455619452474-d2be8b1e70cd?auto=format&fit=crop&w=900&q=75',
    yield: 4,
    state: 'needs_review',
    nutrition: { calories: 441, protein: 13, carbs: 51, fat: 21, basis: 'per_serving' },
    nutritionSource: 'publisher',
    nutritionSourceName: 'Good Food',
    reviewCount: 2,
    mealKinds: ['Dinner']
  },
  {
    id: 'shakshuka',
    title: 'Spiced shakshuka',
    source: 'Saved recipe',
    sourceUrl: '#',
    imageUrl: 'https://images.unsplash.com/photo-1590412200988-a436970781fa?auto=format&fit=crop&w=900&q=75',
    yield: 2,
    state: 'no_nutrition',
    mealKinds: ['Breakfast', 'Lunch', 'Dinner']
  },
  {
    id: 'lemon-greens',
    title: 'Lemon garlic greens',
    source: 'Saved recipe',
    sourceUrl: '#',
    yield: 4,
    state: 'ready',
    nutrition: { calories: 96, protein: 4, carbs: 9, fat: 6, basis: 'per_serving' },
    mealKinds: ['Side']
  },
  {
    id: 'apple-peanut-snack',
    title: 'Apple and peanut butter',
    source: 'Saved recipe',
    sourceUrl: '#',
    yield: 1,
    state: 'ready',
    nutrition: { calories: 248, protein: 8, carbs: 29, fat: 12, basis: 'per_serving' },
    mealKinds: ['Snack']
  }
]

const meal = (id: string, kind: DayPlan['meals'][number]['kind'], title: string, calories: number, protein: number, carbs: number, fat: number, batchLabel?: string) => ({
  id, kind, title, source: 'Saved recipe', portions: 1,
  nutrition: { calories, protein, carbs, fat, basis: 'per_serving' as const }, batchLabel
})

export const demoWeek: DayPlan[] = [
  { date: '2026-07-13', day: 'Monday', shortDate: '13 Jul', targetCalories: 2000, meals: [meal('m1','Breakfast','Berry overnight oats',386,17,56,10),meal('m2','Lunch','Harissa chicken & chickpeas',524,48,39,18,'Batch · day 1 of 3'),meal('m3','Dinner','Spiced shakshuka',418,24,28,23),meal('m4','Snack','Apple & peanut butter',248,8,29,12)] },
  { date: '2026-07-14', day: 'Tuesday', shortDate: '14 Jul', targetCalories: 2000, meals: [meal('t1','Breakfast','Greek yoghurt granola',420,25,52,13),meal('t2','Lunch','Harissa chicken & chickpeas',524,48,39,18,'Leftover · day 2 of 3'),meal('t3','Dinner','Salmon with summer greens',601,45,36,28),meal('t4','Snack','Hummus & carrots',191,7,22,9)] },
  { date: '2026-07-15', day: 'Wednesday', shortDate: '15 Jul', targetCalories: 2000, meals: [meal('w1','Breakfast','Mushroom scrambled eggs',394,29,18,22),meal('w2','Lunch','Harissa chicken & chickpeas',524,48,39,18,'Leftover · day 3 of 3'),meal('w3','Dinner','Fragrant green curry',441,13,51,21),meal('w4','Snack','Banana oat bites',257,8,42,8)] },
  { date: '2026-07-16', day: 'Thursday', shortDate: '16 Jul', targetCalories: 2000, meals: [meal('th1','Breakfast','Berry overnight oats',386,17,56,10),meal('th2','Lunch','Roasted tomato soup',462,18,58,17),meal('th3','Dinner','Wild mushroom risotto',548,18,78,17),meal('th4','Snack','Yoghurt & berries',206,14,24,6)] },
  { date: '2026-07-17', day: 'Friday', shortDate: '17 Jul', targetCalories: 2000, meals: [meal('f1','Breakfast','Greek yoghurt granola',420,25,52,13),meal('f2','Lunch','Roasted tomato soup',462,18,58,17,'Leftover · day 2 of 2'),meal('f3','Dinner','Eating out',620,25,68,26),meal('f4','Snack','Apple & peanut butter',248,8,29,12)] },
  { date: '2026-07-18', day: 'Saturday', shortDate: '18 Jul', targetCalories: 2000, meals: [meal('sa1','Breakfast','Spiced shakshuka',418,24,28,23),meal('sa2','Lunch','Rainbow grain bowl',512,21,71,17),meal('sa3','Dinner','Salmon with summer greens',601,45,36,28)] },
  { date: '2026-07-19', day: 'Sunday', shortDate: '19 Jul', targetCalories: 2000, meals: [meal('su1','Breakfast','Mushroom scrambled eggs',394,29,18,22),meal('su2','Lunch','Rainbow grain bowl',512,21,71,17),meal('su3','Dinner','Fragrant green curry',441,13,51,21)] }
]

export const demoPantry: PantryItem[] = [
  { id: 'p1', name: 'Basmati rice', quantity: 900, unit: 'g', reserved: 450, quantityDisplay: '900 g', reservedDisplay: '450 g', usableDisplay: '450 g', category: 'Cupboard', staple: true },
  { id: 'p2', name: 'Eggs', quantity: 8, unit: 'eggs', reserved: 5, quantityDisplay: '8 eggs', reservedDisplay: '5 eggs', usableDisplay: '3 eggs', category: 'Dairy & eggs', expires: '18 Jul' },
  { id: 'p3', name: 'Greek yoghurt', quantity: 500, unit: 'g', reserved: 350, quantityDisplay: '500 g', reservedDisplay: '350 g', usableDisplay: '150 g', category: 'Dairy & eggs', expires: '15 Jul' },
  { id: 'p4', name: 'Chickpeas', quantity: 3, unit: 'tins', reserved: 2, quantityDisplay: '3 tins', reservedDisplay: '2 tins', usableDisplay: '1 tin', category: 'Cupboard' },
  { id: 'p5', name: 'Olive oil', quantity: 620, unit: 'ml', reserved: 90, quantityDisplay: '620 ml', reservedDisplay: '90 ml', usableDisplay: '530 ml', category: 'Cupboard', staple: true },
  { id: 'p6', name: 'Spinach', quantity: 180, unit: 'g', reserved: 150, quantityDisplay: '180 g', reservedDisplay: '150 g', usableDisplay: '30 g', category: 'Fruit & veg', expires: '14 Jul' }
]

export const initialShopping: ShoppingItem[] = [
  { id: 's1', name: 'Chicken thighs', buy: '1.2 kg', exact: '1.08 kg required', category: 'Meat & fish', checked: false, updatedAt: 1 },
  { id: 's2', name: 'Salmon fillets', buy: '4 fillets', exact: '', category: 'Meat & fish', checked: false, updatedAt: 1 },
  { id: 's3', name: 'Eggs', buy: '6 eggs', exact: '5 eggs required', pantryUsed: '3 eggs reserved from pantry', category: 'Dairy & eggs', checked: false, updatedAt: 1 },
  { id: 's4', name: 'Greek yoghurt', buy: '500 g', exact: '430 g required', pantryUsed: '150 g available in pantry', category: 'Dairy & eggs', checked: true, updatedAt: 1 },
  { id: 's5', name: 'Red peppers', buy: '3 items', exact: '', category: 'Fruit & veg', checked: false, updatedAt: 1 },
  { id: 's6', name: 'Lemons', buy: '2 items', exact: '', category: 'Fruit & veg', checked: false, updatedAt: 1 },
  { id: 's7', name: 'Chickpeas', buy: '2 × 400 g tins', exact: '760 g required', pantryUsed: '1 tin already available', category: 'Cupboard', checked: false, updatedAt: 1 },
  { id: 's8', name: 'Arborio rice', buy: '500 g', exact: '380 g required', category: 'Cupboard', checked: false, updatedAt: 1 }
]
