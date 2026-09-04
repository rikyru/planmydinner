import { defineComponent } from 'vue';
import MensaModal from './mensa.js?v=5';
import RoutineStrip from './routine.js?v=1';

const TodayView = defineComponent({
    name: 'TodayView',
    inject: ['toast'],
    components: { MensaModal, RoutineStrip },
    template: `
        <div class="today-view">
            <h2>Oggi — {{ formattedDate }}</h2>

            <!-- Adherence strip -->
            <div v-if="adherence && adherence.planned_slots > 0" class="adherence-strip">
                <span>Questa settimana: {{ adherence.in_plan_consumed }}/{{ adherence.planned_slots }} pasti</span>
                <div class="adherence-bar-wrap">
                    <div class="adherence-bar-fill" :style="{width: (adherence.adherence_score * 100) + '%'}"></div>
                </div>
                <span class="adherence-score">{{ Math.round(adherence.adherence_score * 100) }}%</span>
            </div>

            <!-- Free meal widget -->
            <div v-if="adherence" class="free-meal-widget">
                <span class="free-meal-count">
                    🎉 Pasti liberi questa settimana: <strong>{{ adherence.free_meals || 0 }}</strong>
                    <span v-if="adherence.free_meal_quota != null"> / {{ adherence.free_meal_quota }}</span>
                </span>
                <span v-if="freeMealMessage" class="free-meal-msg">{{ freeMealMessage }}</span>
            </div>

            <!-- Pasti fissi: colazione & spuntini (opt-out) -->
            <routine-strip v-if="profileA" :profile-id="profileA.id" :meal-date="today"
                           @changed="loadAdherence" />

            <div v-if="loading" class="loading">Caricamento...</div>
            <div v-if="error" class="error">{{ error }}</div>

            <div v-if="!loading && !error && !todayPlan && profiles.length >= 2" class="no-plan-banner">
                <span>Nessun piano per questa settimana: puoi comunque registrare cosa mangi.</span>
                <button @click="generateWeek" :disabled="generating" class="btn-sm btn-secondary">
                    {{ generating ? 'Generazione...' : 'Genera piano' }}
                </button>
            </div>

            <div v-if="!loading && !error && profiles.length < 2">
                <p>Crea almeno 2 profili nella sezione Profili per usare il pianificatore.</p>
            </div>

            <div v-if="displayPlan">
                <div v-for="meal in displayPlan.meals" :key="meal.meal_type" class="meal-box">
                    <div class="meal-header">
                        <h3>{{ meal.meal_type === 'pranzo' ? '🍽 Pranzo' : '🌙 Cena' }}</h3>
                    </div>

                    <div v-if="meal.items && meal.items.length > 0">
                        <!-- Free meal display -->
                        <div v-if="isFree(meal)" class="meal-free-badge">
                            🎉 Pasto libero — {{ meal.items[0].item_name }}
                        </div>

                        <!-- Normal meal content -->
                        <div v-else>
                            <div class="recipe-name">{{ meal.items[0].item_name }}</div>

                            <!-- Componenti inline: protein / carb / verdure -->
                            <div v-if="recipeDetails[meal.meal_type]" class="meal-components">
                                <div v-for="p in getProteins(meal.meal_type)" :key="'p-' + p.name" class="component component-protein">
                                    <span class="component-icon">🥩</span>
                                    <span class="component-label">Proteina</span>
                                    <span class="component-name">{{ p.name }}</span>
                                    <span class="component-grams">{{ getGrams(meal.meal_type, p) }}g</span>
                                </div>
                                <div v-for="c in getCarbs(meal.meal_type)" :key="'c-' + c.name" class="component component-carb">
                                    <span class="component-icon">🌾</span>
                                    <span class="component-label">Carbo</span>
                                    <span class="component-name">{{ c.name }}</span>
                                    <span class="component-grams">{{ getGrams(meal.meal_type, c) }}g</span>
                                </div>
                                <div v-for="veg in getVegetables(meal.meal_type)" :key="veg.name" class="component component-veg">
                                    <span class="component-icon">🥦</span>
                                    <span class="component-label">Verdure</span>
                                    <span class="component-name">{{ veg.name }}</span>
                                    <span class="component-grams">{{ getGrams(meal.meal_type, veg) }}g</span>
                                </div>
                            </div>
                            <div v-else-if="meal.items[0].recipe_id && !recipeDetails[meal.meal_type]" class="components-loading">
                                Caricamento dettagli...
                            </div>
                            <div v-else-if="!meal.items[0].recipe_id" class="components-hint">
                                Cambia ricetta per vedere i dettagli nutrizionali.
                            </div>

                            <!-- Pannello dettaglio espandibile -->
                            <div v-if="expandedMeal === meal.meal_type && recipeDetails[meal.meal_type]" class="detail-panel">
                                <h4>Ingredienti completi</h4>
                                <table class="detail-table">
                                    <thead>
                                        <tr>
                                            <th>Ingrediente</th>
                                            <th>Gruppo</th>
                                            <th v-if="profileA">{{ profileA.name }}</th>
                                            <th v-if="profileB">{{ profileB.name }}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="ing in recipeDetails[meal.meal_type].content" :key="ing.name">
                                            <td>{{ ing.name }}</td>
                                            <td class="group-badge">{{ ing.food_group }}</td>
                                            <td v-if="profileA">{{ formatQty(ing, profileA.id) }}</td>
                                            <td v-if="profileB">{{ formatQty(ing, profileB.id) }}</td>
                                        </tr>
                                    </tbody>
                                </table>
                                <div v-if="getCookingMethod(meal.meal_type)" class="detail-meta">
                                    <span>Cottura: <strong>{{ getCookingMethod(meal.meal_type) }}</strong></span>
                                </div>
                                <div v-if="recipeDetails[meal.meal_type].description" class="detail-meta">
                                    <span>Note: {{ recipeDetails[meal.meal_type].description }}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div v-else class="recipe-name empty">Nessuna ricetta assegnata</div>

                    <!-- Meal actions -->
                    <div class="meal-actions">
                        <!-- Free meal: only show undo -->
                        <template v-if="isFree(meal)">
                            <button @click="cancelFreeMeal(meal.meal_type)" class="btn-undo-free">Annulla pasto libero</button>
                        </template>

                        <!-- Free meal input prompt -->
                        <template v-else-if="showFreeMealPrompt === meal.meal_type">
                            <input v-model="freeMealTitle"
                                   placeholder="Cosa mangi? (es. Pizza)"
                                   style="padding:5px 8px;border:1px solid #ced4da;border-radius:6px;font-size:13px;flex:1;"
                                   @keyup.enter="submitFreeMeal(meal.meal_type)">
                            <button @click="submitFreeMeal(meal.meal_type)" class="btn-free">OK</button>
                            <button @click="showFreeMealPrompt=null" class="btn-secondary">Annulla</button>
                        </template>

                        <!-- Normal meal actions -->
                        <template v-else>
                            <!-- Primary: Ho mangiato / gia' registrato -->
                            <div v-if="isLogged(meal.meal_type)" class="meal-logged-badge">
                                ✓ Pasto registrato
                                <button @click="markConsumed(meal.meal_type)" class="btn-sm btn-secondary" style="margin-left:auto;">↺ registra di nuovo</button>
                            </div>
                            <button v-else-if="meal.items?.[0]?.recipe_id"
                                    @click="markConsumed(meal.meal_type)" class="btn-consumed btn-action-primary">✓ Ho mangiato</button>
                            <div v-else class="components-hint">
                                Registra cosa hai mangiato con "Libero", "Personalizzato" o "Da foto".
                            </div>

                            <!-- Swap row (solo se c'è una ricetta) -->
                            <div v-if="meal.items?.[0]?.recipe_id" class="action-row-swaps">
                                <button @click="openComponentModal(meal.meal_type, meal.items[0].recipe_id, 'carb')"
                                        class="btn-swap">↕ Carbo</button>
                                <button @click="openComponentModal(meal.meal_type, meal.items[0].recipe_id, 'protein')"
                                        class="btn-swap">↕ Proteina</button>
                                <button @click="openComponentModal(meal.meal_type, meal.items[0].recipe_id, 'veg')"
                                        class="btn-swap">↕ Verdura</button>
                            </div>

                            <!-- Secondary actions -->
                            <div class="action-row-secondary">
                                <button @click="openChangeModal(meal.meal_type)" class="btn-secondary">↺ Cambia</button>
                                <button v-if="recipeDetails[meal.meal_type]"
                                        @click="toggleDetail(meal.meal_type)"
                                        class="btn-detail">
                                    {{ expandedMeal === meal.meal_type ? '✕ Chiudi' : '📋 Dettaglio' }}
                                </button>
                                <button @click="openFreeMealPrompt(meal.meal_type)" class="btn-free">🎉 Libero</button>
                                <button @click="openCustomModal(meal.meal_type)" class="btn-secondary">✏️ Personalizzato</button>
                                <button @click="openMensaModal(meal.meal_type)" class="btn-secondary">📷 Da foto</button>
                            </div>
                        </template>
                    </div>
                </div>

                <!-- Segna tutta la giornata con un tap -->
                <div v-if="canMarkDay" style="margin-top:12px;">
                    <button @click="markDayConsumed" class="btn-consumed" :disabled="markingDay">
                        {{ markingDay ? 'Registrazione...' : '✓✓ Segna tutta la giornata come consumata' }}
                    </button>
                </div>
            </div>

            <!-- Modal cambio ricetta / componente -->
            <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
                <div class="modal">
                    <h3>Scegli una ricetta per {{ currentMealType === 'pranzo' ? 'pranzo' : 'cena' }}</h3>
                    <div v-if="loadingOptions" class="loading">Caricamento opzioni...</div>
                    <div v-if="modalError" class="error">{{ modalError }}</div>
                    <div v-for="option in recipeOptions" :key="option.option_id" class="recipe-option"
                         @click="applyRecipe(option.recipe_id)">
                        <strong>{{ option.name }}
                            <span v-if="option.divergence_strategy === 'llm_generated'" class="ai-badge">✨ AI</span>
                        </strong>
                        <span>{{ option.total_time_minutes }} min · {{ option.difficulty }}</span>
                        <span v-if="option.key_ingredients && option.key_ingredients.length">
                            {{ option.key_ingredients.join(', ') }}
                        </span>
                    </div>
                    <div v-if="!loadingOptions" style="display:flex;gap:10px;margin-top:6px;flex-wrap:wrap;">
                        <button @click="requestAiOptions" class="btn-fantasy btn-sm" :disabled="loadingAiOptions">
                            {{ loadingAiOptions ? '✨ Genero...' : '✨ Proponi 3 con AI' }}
                        </button>
                        <button @click="toggleRecipeSearch" class="btn-secondary btn-sm">
                            🔍 Cerca tra le tue ricette
                        </button>
                        <button @click="closeModal" class="btn-secondary">Annulla</button>
                    </div>

                    <div v-if="showRecipeSearch" style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px;">
                        <input v-model="recipeSearchQuery" type="text" placeholder="Cerca per nome..."
                               style="width:100%;box-sizing:border-box;">
                        <div v-if="loadingAllRecipes" class="hint" style="margin-top:6px;">Caricamento ricette...</div>
                        <div v-else style="max-height:260px;overflow-y:auto;margin-top:6px;">
                            <div v-for="r in filteredCatalogRecipes" :key="r.id" class="recipe-option"
                                 @click="applyRecipe(r.id)">
                                <strong>{{ r.name }}</strong>
                                <span>{{ r.total_time_minutes ? r.total_time_minutes + ' min · ' : '' }}{{ r.difficulty }}</span>
                            </div>
                            <div v-if="!filteredCatalogRecipes.length" class="hint">Nessuna ricetta trovata.</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Mensa / foto pasto modal (componente condiviso) -->
            <mensa-modal v-if="showMensaModal"
                         :profile-id="profileA.id"
                         :meal-type="mensaMealType"
                         :meal-date="today"
                         @close="closeMensaModal"
                         @saved="onMensaSaved" />

            <!-- Custom meal modal -->
            <div v-if="showCustomModal" class="modal-overlay" @click.self="showCustomModal=false">
                <div class="modal">
                    <h3>Pasto personalizzato — {{ customMealType === 'pranzo' ? 'Pranzo' : 'Cena' }}</h3>
                    <div class="custom-form">
                        <label>Nome del pasto</label>
                        <input v-model="customForm.title" placeholder="Es. Pollo arrostito con riso">
                        <label>Proteina</label>
                        <div class="custom-row">
                            <input v-model="customForm.protein_name" placeholder="Es. pollo">
                            <input v-model.number="customForm.protein_grams" type="number" placeholder="g">
                        </div>
                        <label>Carboidrato</label>
                        <div class="custom-row">
                            <input v-model="customForm.carb_name" placeholder="Es. riso">
                            <input v-model.number="customForm.carb_grams" type="number" placeholder="g">
                        </div>
                        <label>Verdura (opzionale)</label>
                        <div class="custom-row">
                            <input v-model="customForm.veg_name" placeholder="Es. zucchine">
                            <input v-model.number="customForm.veg_grams" type="number" min="0" step="10" placeholder="g" style="width:70px">
                        </div>
                        <label>Note (opzionale)</label>
                        <input v-model="customForm.notes" placeholder="...">
                    </div>
                    <div style="display:flex;gap:10px;margin-top:16px;">
                        <button @click="submitCustomMeal"
                                class="btn-consumed"
                                :disabled="!customForm.title || !customForm.protein_name || !customForm.carb_name">
                            Applica
                        </button>
                        <button @click="showCustomModal=false" class="btn-secondary">Annulla</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            dailyPlans: [],
            todayPlan: null,
            recipeDetails: {},   // keyed by meal_type ('pranzo'/'cena')
            expandedMeal: null,  // meal_type currently expanded
            loading: false,
            error: null,
            generating: false,
            showModal: false,
            currentMealType: null,
            recipeOptions: [],
            loadingOptions: false,
            loadingAiOptions: false,
            modalError: null,
            // Ricerca libera tra le proprie ricette (modal cambio ricetta)
            showRecipeSearch: false,
            allRecipes: [],
            loadingAllRecipes: false,
            recipeSearchQuery: '',
            today: new Date().toISOString().slice(0, 10),
            // Adherence
            adherence: null,
            todayStatus: null,
            // Free meal
            showFreeMealPrompt: null,
            freeMealTitle: '',
            // Mark whole day
            markingDay: false,
            // Mensa / foto pasto
            showMensaModal: false,
            mensaMealType: null,
            // Custom meal
            showCustomModal: false,
            customForm: { title: '', protein_name: '', protein_grams: 0, carb_name: '', carb_grams: 0, veg_name: '', veg_grams: 100, notes: '' },
            customMealType: null,
        };
    },
    computed: {
        formattedDate() {
            const d = new Date(this.today + 'T12:00:00');
            return d.toLocaleDateString('it-IT', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
        },
        profileA() { return this.profiles[0] || null; },
        profileB() { return this.profiles[1] || null; },
        displayPlan() {
            // Senza piano si mostrano comunque pranzo e cena vuoti, così si può
            // registrare cosa si è mangiato: il backend crea il piano al volo e la
            // generazione successiva riempirà solo gli slot rimasti liberi.
            if (this.todayPlan) return this.todayPlan;
            if (!this.profiles.length || this.loading || this.error) return null;
            return {
                date: this.today,
                meals: [
                    { meal_type: 'pranzo', items: [] },
                    { meal_type: 'cena', items: [] },
                ],
            };
        },
        filteredCatalogRecipes() {
            const q = this.recipeSearchQuery.trim().toLowerCase();
            const list = q
                ? this.allRecipes.filter(r => (r.name || '').toLowerCase().includes(q))
                : this.allRecipes;
            return list.slice(0, 30);
        },
        canMarkDay() {
            if (this.todayStatus && this.todayStatus.unlogged_count === 0) return false;
            return (this.todayPlan?.meals || []).some(m =>
                m.items?.[0]?.recipe_id && !['free_meal', 'not_eaten'].includes(m.items[0].food_group));
        },
        freeMealMessage() {
            if (!this.adherence) return '';
            const used = this.adherence.free_meals || 0;
            const quota = this.adherence.free_meal_quota;
            if (quota == null) return used === 0 ? '🌟 Nessun pasto libero questa settimana!' : '';
            const remaining = quota - used;
            if (used === 0) return '🌟 Ottimo, nessun pasto libero!';
            if (remaining > 1) return `💪 Hai ancora ${remaining} pasti liberi`;
            if (remaining === 1) return '⚠️ Ultimo pasto libero disponibile';
            if (remaining === 0) return '😊 Raggiunto il limite settimanale';
            return `⚠️ Superato il limite di ${Math.abs(remaining)} pasti`;
        },
    },
    mounted() {
        this.loadData();
    },
    methods: {
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const resp = await window.apiFetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) {
                    await this.loadWeeklyPlan();
                    await this.loadAdherence();
                }
            } catch (e) {
                this.error = 'Errore nel caricamento dei profili: ' + e.message;
            } finally {
                this.loading = false;
            }
        },
        async loadWeeklyPlan() {
            // Use plan-for-date to find any saved plan covering today (rolling, any start_date)
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB.id,
                target_date: this.today,
            });
            const resp = await window.apiFetch('/planner/plan-for-date?' + params);
            if (!resp.ok || resp.status === 204) {
                this.dailyPlans = [];
                this.todayPlan = null;
                return;
            }
            const result = await resp.json();
            if (!result) {
                this.dailyPlans = [];
                this.todayPlan = null;
                return;
            }
            this.dailyPlans = result.daily_plans || [];
            this.todayPlan = this.dailyPlans.find(d => d.date === this.today) || null;
            this.recipeDetails = {};
            await this.fetchRecipeDetails();
        },
        async fetchRecipeDetails() {
            if (!this.todayPlan) return;
            for (const meal of this.todayPlan.meals) {
                const recipeId = meal.items?.[0]?.recipe_id;
                if (!recipeId) continue;
                try {
                    const resp = await window.apiFetch(`/recipes/detail/${recipeId}`);
                    if (resp.ok) {
                        this.recipeDetails[meal.meal_type] = await resp.json();
                    }
                } catch (_) { /* non bloccare il caricamento principale */ }
            }
        },
        async loadAdherence() {
            if (!this.profileA) return;
            try {
                const params = new URLSearchParams({ profile_id_A: this.profileA.id });
                const resp = await window.apiFetch('/planner/adherence?' + params);
                if (resp.ok) this.adherence = await resp.json();
            } catch (_) { /* non bloccare */ }
            try {
                const resp = await window.apiFetch('/integration/today-status?profile_id=' + encodeURIComponent(this.profileA.id));
                if (resp.ok) this.todayStatus = await resp.json();
            } catch (_) { /* non bloccare */ }
        },
        isLogged(mealType) {
            const m = (this.todayStatus?.meals || []).find(x => x.meal_type === mealType);
            return !!m?.logged;
        },
        async generateWeek() {
            this.generating = true;
            this.error = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    current_date: this.today,
                });
                const resp = await window.apiFetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const allDays = await resp.json();
                this.dailyPlans = allDays;
                this.todayPlan = allDays.find(d => d.date === this.today) || null;
                this.recipeDetails = {};
                await this.fetchRecipeDetails();
                await this.loadAdherence();
            } catch (e) {
                this.error = 'Errore nella generazione del piano: ' + e.message;
            } finally {
                this.generating = false;
            }
        },
        async openChangeModal(mealType) {
            this.currentMealType = mealType;
            this.recipeOptions = [];
            this.modalError = null;
            this.loadingOptions = true;
            this.showModal = true;
            try {
                // Solo catalogo (le tue ricette): veloce, nessuna chiamata AI.
                // L'AI parte solo su richiesta esplicita (bottone "Proponi con AI")
                // o in automatico solo se il catalogo non ha nessuna opzione.
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: this.today,
                });
                const resp = await window.apiFetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.recipeOptions = await resp.json();
            } catch (e) {
                this.modalError = 'Errore nel caricamento opzioni: ' + e.message;
            } finally {
                this.loadingOptions = false;
            }
        },
        async requestAiOptions() {
            this.loadingAiOptions = true;
            this.modalError = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.currentMealType,
                    current_date: this.today,
                    use_llm_fill: 'true',
                    target_count: this.recipeOptions.length + 3,
                });
                const resp = await window.apiFetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const all = await resp.json();
                const known = new Set(this.recipeOptions.map(o => o.recipe_id));
                const fresh = all.filter(o => o.divergence_strategy === 'llm_generated' && !known.has(o.recipe_id));
                this.recipeOptions = [...this.recipeOptions, ...fresh];
                if (!fresh.length) this.toast.add('Nessuna nuova proposta AI.', 'info');
            } catch (e) {
                this.modalError = 'Errore nella generazione AI: ' + e.message;
            } finally {
                this.loadingAiOptions = false;
            }
        },
        async applyRecipe(recipeId) {
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.currentMealType,
                    current_date: this.today,
                    recipe_id: recipeId,
                });
                const resp = await window.apiFetch('/planner/apply-recipe-option?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeModal();
                await this.loadWeeklyPlan();
            } catch (e) {
                this.modalError = "Errore nell'applicazione della ricetta: " + e.message;
            }
        },
        async markConsumed(mealType) {
            if (!this.profileA) return;
            try {
                const meal = this.todayPlan?.meals.find(m => m.meal_type === mealType);
                const recipeId = meal?.items?.[0]?.recipe_id || null;
                const body = {
                    profile_id: this.profileA.id,
                    date: this.today,
                    meal_type: mealType,
                    type: 'planned',
                    consumed_recipe_id: recipeId,
                };
                const resp = await window.apiFetch('/consumed-entries/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio.');
                this.toast.add('Pasto registrato!', 'success');
                await this.loadAdherence();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        async markDayConsumed() {
            if (!this.profileA) return;
            this.markingDay = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileA.id, day: this.today });
                const resp = await window.apiFetch('/consumed-entries/mark-day?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const result = await resp.json();
                this.toast.add(result.marked > 0
                    ? `Registrati ${result.marked} pasti di oggi!`
                    : 'Nessun pasto da registrare (già segnati o senza ricetta).',
                    result.marked > 0 ? 'success' : 'info');
                await this.loadAdherence();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.markingDay = false;
            }
        },
        toggleDetail(mealType) {
            this.expandedMeal = this.expandedMeal === mealType ? null : mealType;
        },
        async openComponentModal(mealType, recipeId, component) {
            this.currentMealType = mealType;
            this.recipeOptions = [];
            this.modalError = null;
            this.loadingOptions = true;
            this.showModal = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: this.today,
                    recipe_id: recipeId,
                    component,
                });
                const resp = await window.apiFetch('/planner/change-component?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.recipeOptions = await resp.json();
            } catch (e) {
                this.modalError = 'Errore nel caricamento alternative: ' + e.message;
            } finally {
                this.loadingOptions = false;
            }
        },
        closeModal() {
            this.showModal = false;
            this.currentMealType = null;
            this.recipeOptions = [];
            this.modalError = null;
            this.showRecipeSearch = false;
            this.recipeSearchQuery = '';
        },
        async toggleRecipeSearch() {
            this.showRecipeSearch = !this.showRecipeSearch;
            if (this.showRecipeSearch && !this.allRecipes.length) {
                this.loadingAllRecipes = true;
                try {
                    const resp = await window.apiFetch('/recipes/');
                    const data = resp.ok ? await resp.json() : [];
                    this.allRecipes = [...data].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
                } catch (_) {
                    this.allRecipes = [];
                } finally {
                    this.loadingAllRecipes = false;
                }
            }
        },

        // --- Free meal ---
        isFree(meal) {
            return meal.items?.[0]?.food_group === 'free_meal';
        },
        openFreeMealPrompt(mealType) {
            this.showFreeMealPrompt = mealType;
            this.freeMealTitle = '';
        },
        async submitFreeMeal(mealType) {
            if (!this.freeMealTitle.trim()) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: this.today,
                });
                const resp = await window.apiFetch('/planner/free-meal?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: this.freeMealTitle, notes: '' }),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.showFreeMealPrompt = null;
                this.freeMealTitle = '';
                await this.loadWeeklyPlan();
                await this.loadAdherence();
                this.toast.add('Pasto libero impostato!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        async cancelFreeMeal(mealType) {
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: this.today,
                });
                const resp = await window.apiFetch('/planner/free-meal?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                await this.loadWeeklyPlan();
                await this.loadAdherence();
                this.toast.add('Pasto libero annullato.', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },

        // --- Mensa / foto pasto ---
        openMensaModal(mealType) {
            this.mensaMealType = mealType;
            this.showMensaModal = true;
        },
        closeMensaModal() {
            this.showMensaModal = false;
            this.mensaMealType = null;
        },
        async onMensaSaved() {
            // il backend ha sostituito lo slot del piano col pasto mensa: ricarica
            await this.loadWeeklyPlan();
            await this.loadAdherence();
        },

        // --- Custom meal ---
        openCustomModal(mealType) {
            this.customMealType = mealType;
            this.customForm = { title: '', protein_name: '', protein_grams: 0, carb_name: '', carb_grams: 0, veg_name: '', notes: '' };
            this.showCustomModal = true;
        },
        async submitCustomMeal() {
            if (!this.customForm.title || !this.customForm.protein_name || !this.customForm.carb_name) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.customMealType,
                    current_date: this.today,
                });
                const resp = await window.apiFetch('/planner/set-custom-meal?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.customForm),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.showCustomModal = false;
                await this.loadWeeklyPlan();
                await this.loadAdherence();
                this.toast.add('Pasto personalizzato applicato!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },

        // --- Helper per i componenti del pasto ---
        getProteins(mealType) {
            const d = this.recipeDetails[mealType];
            if (!d) return [];
            const PROT = ['proteina', 'proteine', 'pollo', 'carne_bianca', 'carne_rossa', 'pesce',
                          'legumi', 'uova', 'latticini', 'formaggio'];
            return d.content.filter(i => PROT.includes((i.food_group || '').toLowerCase()));
        },
        getCarbs(mealType) {
            const d = this.recipeDetails[mealType];
            if (!d) return [];
            return d.content.filter(i => ['carboidrati', 'carboidrato'].includes((i.food_group || '').toLowerCase()));
        },
        getVegetables(mealType) {
            const d = this.recipeDetails[mealType];
            if (!d) return [];
            return d.content.filter(i => i.food_group === 'verdure');
        },
        getGrams(mealType, ingredient) {
            if (!ingredient || !this.profileA) return '?';
            const qty = ingredient.quantities?.[this.profileA.id];
            const g = qty?.grams_equiv ?? qty?.qty ?? null;
            return g !== null ? Math.round(g) : '?';
        },
        formatQty(ingredient, profileId) {
            const qty = ingredient.quantities?.[profileId];
            if (!qty) return '—';
            const g = qty.grams_equiv ?? qty.qty;
            return `${Math.round(g)}${qty.unit !== 'g' ? ' ' + qty.unit : 'g'}`;
        },
        getCookingMethod(mealType) {
            const d = this.recipeDetails[mealType];
            if (!d) return null;
            return d.tags?.cooking_methods?.[0] || null;
        },
    },
});

export default TodayView;
