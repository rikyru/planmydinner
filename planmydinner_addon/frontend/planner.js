import { defineComponent } from 'vue';

const WeekView = defineComponent({
    name: 'WeekView',
    inject: ['toast'],
    template: `
        <div class="week-layout" @click="closeMealMenu">

            <!-- ── Sidebar ────────────────────────────────────────────── -->
            <aside class="week-sidebar">
                <h2 class="sidebar-title">Settimana</h2>

                <div class="sidebar-field">
                    <label class="sidebar-label">Dal</label>
                    <input type="date" v-model="startDate" @change="onStartDateChange" />
                    <span class="sidebar-range">→ {{ endDateLabel }}</span>
                </div>

                <div class="sidebar-actions">
                    <button @click.stop="goToToday" class="btn-today sidebar-btn">Oggi</button>
                    <template v-if="!loading && profiles.length >= 2">
                        <button @click.stop="generateWeek(false)" :disabled="generating"
                                class="btn-regenerate sidebar-btn">
                            {{ generating ? 'Generando...' : 'Rigenera' }}
                        </button>
                        <button @click.stop="generateWeek(true)" :disabled="generating"
                                class="btn-fantasy sidebar-btn"
                                title="Usa LLM per inventare ricette creative ad ogni slot">
                            {{ generating ? 'Generando...' : '✨ ExtraFantasy' }}
                        </button>
                    </template>
                </div>

                <div v-if="loading" class="loading" style="margin-top:16px">Caricamento...</div>
                <div v-if="error" class="error-box" style="margin-top:12px">{{ error }}</div>
                <div v-if="!loading && profiles.length < 2" class="hint" style="margin-top:12px">
                    Crea almeno 2 profili per usare il pianificatore.
                </div>
            </aside>

            <!-- ── Area principale ───────────────────────────────────── -->
            <div class="week-main">

                <!-- Nessun piano -->
                <div v-if="!loading && profiles.length >= 2 && !weekPlan && !error" class="no-plan">
                    <p>Nessun piano per questa settimana.</p>
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        <button @click.stop="generateWeek(false)" :disabled="generating" class="btn-primary">
                            {{ generating ? 'Generazione...' : 'Genera piano 7 giorni' }}
                        </button>
                        <button @click.stop="generateWeek(true)" :disabled="generating" class="btn-fantasy"
                                title="Usa LLM per inventare ricette creative ad ogni slot">
                            {{ generating ? 'Generando...' : '✨ ExtraFantasy' }}
                        </button>
                    </div>
                </div>

                <!-- Griglia giorni -->
                <div v-if="weekPlan" class="week-grid">
                    <article v-for="day in weekPlan" :key="day.date"
                             class="day-card" :class="{ 'day-card--today': isToday(day.date) }">

                        <header class="day-card__header">
                            <div class="day-card__names">
                                <span class="day-name">{{ formatDayName(day.date) }}</span>
                                <span class="day-date">{{ formatShortDate(day.date) }}</span>
                            </div>
                            <span v-if="isToday(day.date)" class="today-badge">Oggi</span>
                        </header>

                        <div class="day-card__meals">
                            <template v-if="day.meals && day.meals.length > 0">
                                <div v-for="meal in day.meals" :key="meal.meal_type"
                                     class="meal-row"
                                     :class="{ 'meal-row--not-eaten': isNotEaten(meal), 'meal-row--free': isFree(meal) }">
                                    <div class="meal-row__info" @click.stop="openMealModal(day.date, meal)">
                                        <span class="meal-row__icon">{{ meal.meal_type === 'pranzo' ? '☀️' : '🌙' }}</span>
                                        <span class="meal-row__type">{{ meal.meal_type === 'pranzo' ? 'Pranzo' : 'Cena' }}</span>
                                        <span v-if="isNotEaten(meal)" class="meal-badge meal-badge--not-eaten">✗</span>
                                        <span v-else-if="isFree(meal)" class="meal-badge meal-badge--free">🎉</span>
                                        <span class="meal-row__name">{{ meal.items?.[0]?.item_name || '—' }}</span>
                                    </div>
                                    <div class="meal-row__menu-wrap">
                                        <span v-if="fantasyApplying === day.date + '_' + meal.meal_type"
                                              class="fantasy-spinner" title="ExtraFantasy in corso...">✨</span>
                                        <button v-else class="btn-meal-menu"
                                                @click.stop="toggleMealMenu(day.date, meal.meal_type)"
                                                :aria-label="'Azioni ' + meal.meal_type">⋯</button>
                                        <div v-if="activeMealMenu === day.date + '_' + meal.meal_type"
                                             class="meal-menu" @click.stop>
                                            <button v-if="meal.items?.[0]?.recipe_id"
                                                    @click="menuOpenComponent(day.date, meal, 'carb')">↕ Carboidrato</button>
                                            <button v-if="meal.items?.[0]?.recipe_id"
                                                    @click="menuOpenComponent(day.date, meal, 'protein')">↕ Proteina</button>
                                            <button v-if="meal.items?.[0]?.recipe_id"
                                                    @click="menuOpenComponent(day.date, meal, 'veg')">↕ Verdura</button>
                                            <button class="meal-menu__change"
                                                    @click="menuChangeRecipe(day.date, meal.meal_type)">↺ Cambia ricetta</button>
                                            <button class="meal-menu__fantasy"
                                                    @click="applyFantasySlot(day.date, meal.meal_type)">✨ ExtraFantasy</button>
                                        </div>
                                    </div>
                                </div>
                            </template>
                            <div v-else class="no-meals">Nessun pasto pianificato</div>
                        </div>
                    </article>
                </div>
            </div>

            <!-- ── Modal pasto (click su meal-row__info) ─────────────── -->
            <div v-if="showMealModal" class="modal-overlay" @click.self="closeMealModal">
                <div class="modal">
                    <h3>
                        {{ mealModalMeal?.meal_type === 'pranzo' ? '☀️' : '🌙' }}
                        {{ mealModalMeal?.meal_type === 'pranzo' ? 'Pranzo' : 'Cena' }}
                        <span style="font-weight:400; font-size:14px; color:#868e96">
                            — {{ formatDateLabel(mealModalDate) }}
                        </span>
                    </h3>

                    <!-- Vista ricetta -->
                    <div v-if="mealRecipeDetail">
                        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                            <button @click="mealRecipeDetail = null" class="btn-secondary">← Nascondi</button>
                            <span style="font-size:13px; color:#555;">
                                {{ mealRecipeDetail.total_time_minutes }} min · {{ mealRecipeDetail.difficulty }}
                            </span>
                        </div>
                        <p v-if="mealRecipeDetail.description" style="font-size:13px; color:#495057; margin:0 0 12px;">
                            {{ mealRecipeDetail.description }}
                        </p>
                        <h4 style="margin:0 0 8px; font-size:14px;">Ingredienti</h4>
                        <ul class="recipe-detail-list">
                            <li v-for="ing in flatIngredients" :key="ing.name">
                                <span>{{ ing.name }}</span>
                                <span class="recipe-detail-grams">{{ ing.grams }}g</span>
                            </li>
                        </ul>
                        <div v-if="mealRecipeDetail.steps && mealRecipeDetail.steps.length > 0">
                            <h4 style="margin:12px 0 8px; font-size:14px;">Preparazione</h4>
                            <ol class="recipe-detail-steps">
                                <li v-for="step in mealRecipeDetail.steps" :key="step">{{ step }}</li>
                            </ol>
                        </div>
                    </div>

                    <!-- Vista principale -->
                    <div v-else-if="!mealModalComponent">
                        <p style="font-weight:600; margin:8px 0 12px; font-size:15px;">
                            {{ mealModalMeal?.items?.[0]?.item_name || '—' }}
                        </p>

                        <!-- Azioni componenti (solo per pasti normali con recipe_id) -->
                        <template v-if="mealModalMeal?.items?.[0]?.recipe_id && !isNotEaten(mealModalMeal) && !isFree(mealModalMeal)">
                            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
                                <button @click="openMealComponent('carb')" class="btn-swap">↕ Carbo</button>
                                <button @click="openMealComponent('protein')" class="btn-swap">↕ Proteina</button>
                                <button @click="openMealComponent('veg')" class="btn-swap">↕ Verdura</button>
                            </div>
                        </template>

                        <!-- Azioni cambio ricetta (solo per pasti normali) -->
                        <template v-if="!isNotEaten(mealModalMeal) && !isFree(mealModalMeal)">
                            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
                                <button @click="openChangeFromMeal" class="btn-secondary">↺ Cambia ricetta</button>
                                <button @click="applyFantasySlot(mealModalDate, mealModalMeal.meal_type, true)"
                                        :disabled="mealModalApplying" class="btn-fantasy" style="font-size:13px; padding:7px 12px;">
                                    {{ mealModalApplying ? '✨...' : '✨ ExtraFantasy' }}
                                </button>
                                <button @click="mealModalComponent = 'custom'" class="btn-secondary">✏️ Personalizzato</button>
                            </div>
                            <div v-if="mealModalMeal?.items?.[0]?.recipe_id" style="margin-bottom:10px;">
                                <button @click="loadRecipeDetail" :disabled="loadingRecipe" class="btn-secondary">
                                    {{ loadingRecipe ? 'Caricamento...' : '📋 Vedi ricetta' }}
                                </button>
                            </div>
                        </template>

                        <!-- Azioni per pasti passati -->
                        <template v-if="isPast(mealModalDate)">
                            <hr style="border:none; border-top:1px solid #dee2e6; margin:10px 0;">

                            <!-- Pasto già segnato come non mangiato -->
                            <div v-if="isNotEaten(mealModalMeal)" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                <span class="meal-status-badge meal-status-badge--not-eaten">✗ Non mangiato</span>
                                <button @click="cancelNotEaten" class="btn-secondary">↩ Ripristina slot</button>
                            </div>

                            <!-- Pasto già segnato come pasto libero -->
                            <div v-else-if="isFree(mealModalMeal)" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                <span class="meal-status-badge meal-status-badge--free">🎉 Pasto libero</span>
                                <button @click="cancelFreeMealFromWeek" class="btn-secondary">↩ Ripristina slot</button>
                            </div>

                            <!-- Pasto normale passato: mostra opzioni -->
                            <div v-else>
                                <div v-if="!showFreeMealInput" style="display:flex; gap:8px; flex-wrap:wrap;">
                                    <button @click="markNotEaten" :disabled="mealModalApplying" class="btn-not-eaten">
                                        {{ mealModalApplying ? '...' : '✗ Non mangiato' }}
                                    </button>
                                    <button @click="openFreeMealInput" class="btn-secondary">🎉 Pasto libero</button>
                                </div>
                                <div v-else style="display:flex; gap:8px; align-items:center; margin-top:6px; flex-wrap:wrap;">
                                    <input v-model="freeMealModalTitle" type="text"
                                           placeholder="Cosa hai mangiato? (opzionale)"
                                           style="flex:1; min-width:160px;"
                                           @keyup.enter="confirmFreeMeal" />
                                    <button @click="confirmFreeMeal" :disabled="mealModalApplying" class="btn-primary">
                                        {{ mealModalApplying ? '...' : 'OK' }}
                                    </button>
                                    <button @click="showFreeMealInput = false" class="btn-secondary">Annulla</button>
                                </div>
                            </div>
                        </template>

                        <div v-if="mealModalError" class="error-box" style="margin-top:10px">{{ mealModalError }}</div>
                    </div>

                    <!-- Vista alternativa componente -->
                    <div v-else-if="mealModalComponent !== 'custom'">
                        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
                            <button @click="mealModalComponent = null; mealModalOptions = []" class="btn-secondary">← Indietro</button>
                            <span style="font-size:14px; color:#555;">
                                Cambia {{ mealModalComponent === 'carb' ? 'carboidrato' : mealModalComponent === 'protein' ? 'proteina' : 'verdura' }}
                            </span>
                        </div>
                        <div v-if="mealModalApplying" class="loading">Caricamento...</div>
                        <div v-if="mealModalError" class="error-box">{{ mealModalError }}</div>
                        <div v-for="option in mealModalOptions" :key="option.option_id"
                             class="recipe-option" @click="applyMealOption(option.recipe_id)">
                            <strong>{{ option.name }}</strong>
                            <span>{{ option.total_time_minutes }} min · {{ option.difficulty }}</span>
                            <span v-if="option.key_ingredients && option.key_ingredients.length">
                                {{ option.key_ingredients.join(', ') }}
                            </span>
                        </div>
                        <div v-if="!mealModalApplying && !mealModalError && mealModalOptions.length === 0" class="hint">
                            Nessuna alternativa trovata.
                        </div>
                    </div>

                    <!-- Vista pasto personalizzato -->
                    <div v-else>
                        <div style="display:flex; align-items:center; gap:10px; margin-bottom:16px;">
                            <button @click="mealModalComponent = null" class="btn-secondary">← Indietro</button>
                            <span style="font-size:14px; color:#555;">Inserisci pasto manualmente</span>
                        </div>
                        <div v-if="mealModalError" class="error-box" style="margin-bottom:12px">{{ mealModalError }}</div>
                        <div class="custom-meal-form">
                            <div class="custom-meal-field">
                                <label>Nome pasto</label>
                                <input v-model="customMeal.title" placeholder="es. Pasta al pomodoro" @keyup.enter="submitCustomMeal" />
                            </div>
                            <div class="custom-meal-row">
                                <div class="custom-meal-field">
                                    <label>🌾 Carboidrato</label>
                                    <input v-model="customMeal.carb_name" placeholder="es. pasta" />
                                </div>
                                <div class="custom-meal-field custom-meal-field--sm">
                                    <label>Grammi</label>
                                    <input v-model.number="customMeal.carb_grams" type="number" min="0" placeholder="80" />
                                </div>
                            </div>
                            <div class="custom-meal-row">
                                <div class="custom-meal-field">
                                    <label>🥩 Proteina</label>
                                    <input v-model="customMeal.protein_name" placeholder="es. pollo" />
                                </div>
                                <div class="custom-meal-field custom-meal-field--sm">
                                    <label>Grammi</label>
                                    <input v-model.number="customMeal.protein_grams" type="number" min="0" placeholder="120" />
                                </div>
                            </div>
                            <div class="custom-meal-row">
                                <div class="custom-meal-field">
                                    <label>🥦 Verdura <span style="color:#adb5bd">(opzionale)</span></label>
                                    <input v-model="customMeal.veg_name" placeholder="es. zucchine" />
                                </div>
                                <div class="custom-meal-field custom-meal-field--sm">
                                    <label>Grammi</label>
                                    <input v-model.number="customMeal.veg_grams" type="number" min="0" placeholder="150" />
                                </div>
                            </div>
                            <div class="custom-meal-field">
                                <label>Note <span style="color:#adb5bd">(opzionale)</span></label>
                                <input v-model="customMeal.notes" placeholder="cottura, variante, ecc." />
                            </div>
                        </div>
                        <button @click="submitCustomMeal" :disabled="mealModalApplying"
                                class="btn-primary" style="margin-top:14px; width:100%">
                            {{ mealModalApplying ? 'Salvataggio...' : '✓ Salva pasto' }}
                        </button>
                    </div>

                    <button @click="closeMealModal" class="btn-secondary" style="margin-top:14px">Chiudi</button>
                </div>
            </div>

            <!-- ── Modal cambio ricetta (↺) ──────────────────────────── -->
            <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
                <div class="modal">
                    <h3>Cambia — {{ currentMealType === 'pranzo' ? 'Pranzo' : 'Cena' }}
                        <span style="font-weight:400; font-size:14px; color:#868e96">
                            {{ formatDateLabel(currentDate) }}
                        </span>
                    </h3>
                    <div v-if="loadingOptions" class="loading">Caricamento opzioni...</div>
                    <div v-if="modalError" class="error-box">{{ modalError }}</div>
                    <div v-for="option in recipeOptions" :key="option.option_id"
                         class="recipe-option" @click="applyRecipe(option.recipe_id)">
                        <strong>{{ option.name }}</strong>
                        <span>{{ option.total_time_minutes }} min · {{ option.difficulty }}</span>
                        <span v-if="option.key_ingredients && option.key_ingredients.length">
                            {{ option.key_ingredients.join(', ') }}
                        </span>
                    </div>
                    <div v-if="!loadingOptions && !modalError && recipeOptions.length === 0" class="hint">
                        Nessuna alternativa trovata per questo slot.
                    </div>
                    <button @click="closeModal" class="btn-secondary" style="margin-top:12px">Annulla</button>
                </div>
            </div>

        </div>
    `,
    data() {
        const now = new Date();
        const today = now.toISOString().slice(0, 10);
        // Snap to Monday (0=Sun → 6 days back, 1=Mon → 0, ..., 6=Sat → 5 days back)
        const dayOfWeek = now.getDay(); // 0=Sun
        const daysToMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
        const monday = new Date(now);
        monday.setDate(now.getDate() - daysToMonday);
        const mondayStr = monday.toISOString().slice(0, 10);
        return {
            profiles: [],
            startDate: mondayStr,
            weekPlan: null,
            loading: false,
            error: null,
            generating: false,
            today,
            // Menu ⋯
            activeMealMenu: null,
            // Modal cambio ricetta (↺)
            showModal: false,
            currentDate: null,
            currentMealType: null,
            recipeOptions: [],
            loadingOptions: false,
            modalError: null,
            // Modal pasto (click su meal-row__info)
            showMealModal: false,
            mealModalDate: null,
            mealModalMeal: null,
            mealModalComponent: null,
            mealModalOptions: [],
            mealModalApplying: false,
            mealModalError: null,
            // Form pasto personalizzato
            customMeal: { title: '', protein_name: '', protein_grams: 120, carb_name: '', carb_grams: 80, veg_name: '', veg_grams: 150, notes: '' },
            // ExtraFantasy per singolo slot
            fantasyApplying: null,
            // Non mangiato / Pasto libero (pasti passati)
            freeMealModalTitle: '',
            showFreeMealInput: false,
            // Vista ricetta
            mealRecipeDetail: null,
            loadingRecipe: false,
        };
    },
    computed: {
        profileA() { return this.profiles[0] || null; },
        profileB() { return this.profiles[1] || null; },
        endDateLabel() {
            if (!this.startDate) return '';
            const end = new Date(this.startDate + 'T12:00:00');
            end.setDate(end.getDate() + 6);
            return end.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        },
        flatIngredients() {
            if (!this.mealRecipeDetail) return [];
            const content = this.mealRecipeDetail.content;
            const items = Array.isArray(content) ? content : (content?.components || []);
            return items.map(ing => {
                const qties = ing.quantities || {};
                const key = Object.keys(qties)[0];
                const g = key ? Math.round(qties[key].grams_equiv || qties[key].qty) : '?';
                return { name: ing.name, grams: g };
            });
        },
    },
    mounted() {
        this.loadData();
        this._outsideClick = () => { this.activeMealMenu = null; };
        document.addEventListener('click', this._outsideClick);
    },
    beforeUnmount() {
        document.removeEventListener('click', this._outsideClick);
    },
    methods: {
        // ── Dati ─────────────────────────────────────────────────────────────
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const resp = await fetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) await this.loadWeekPlan();
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            } finally {
                this.loading = false;
            }
        },
        async loadWeekPlan() {
            if (!this.profileA) return;
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB?.id || '',
                start_date: this.startDate,
            });
            const resp = await fetch('/planner/weekly-plan?' + params);
            if (resp.ok) {
                this.weekPlan = await resp.json();
            } else if (resp.status === 404) {
                this.weekPlan = null;
            } else {
                this.error = 'Errore nel caricamento del piano.';
            }
        },
        async generateWeek(fantasyMode = false) {
            if (!this.profileA || !this.profileB) return;
            this.generating = true;
            this.error = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    current_date: this.startDate,
                    fantasy_mode: fantasyMode,
                });
                const resp = await fetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.weekPlan = await resp.json();
                this.toast.add(fantasyMode ? '✨ Piano ExtraFantasy generato!' : 'Piano generato!', 'success');
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            } finally {
                this.generating = false;
            }
        },

        // ── Menu ⋯ ───────────────────────────────────────────────────────────
        toggleMealMenu(dateStr, mealType) {
            const key = dateStr + '_' + mealType;
            this.activeMealMenu = this.activeMealMenu === key ? null : key;
        },
        closeMealMenu() {
            this.activeMealMenu = null;
        },
        async menuOpenComponent(dateStr, meal, component) {
            this.closeMealMenu();
            this.openMealModal(dateStr, meal);
            await this.openMealComponent(component);
        },
        menuChangeRecipe(dateStr, mealType) {
            this.closeMealMenu();
            this.openChangeModal(dateStr, mealType);
        },
        async applyFantasySlot(dateStr, mealType, fromModal = false) {
            if (!this.profileA || !this.profileB) return;
            this.closeMealMenu();
            if (fromModal) {
                this.mealModalApplying = true;
                this.mealModalError = null;
            } else {
                this.closeMealModal();
                this.fantasyApplying = dateStr + '_' + mealType;
            }
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: dateStr,
                });
                const resp = await fetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const options = await resp.json();
                if (!options.length) throw new Error('Nessuna ricetta trovata dall\'LLM.');
                const applyParams = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: dateStr,
                    recipe_id: options[0].recipe_id,
                });
                const applyResp = await fetch('/planner/apply-recipe-option?' + applyParams, { method: 'POST' });
                if (!applyResp.ok) throw new Error(await applyResp.text());
                if (fromModal) this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('✨ Ricetta ExtraFantasy applicata!', 'success');
            } catch (e) {
                if (fromModal) this.mealModalError = 'Errore: ' + e.message;
                else this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.fantasyApplying = null;
                if (fromModal) this.mealModalApplying = false;
            }
        },

        // ── Modal cambio ricetta (↺) ──────────────────────────────────────
        async openChangeModal(dateStr, mealType) {
            if (!this.profileA || !this.profileB) return;
            this.currentDate = dateStr;
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
                    current_date: dateStr,
                });
                const resp = await fetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.recipeOptions = await resp.json();
            } catch (e) {
                this.modalError = 'Errore nel caricamento opzioni: ' + e.message;
            } finally {
                this.loadingOptions = false;
            }
        },
        async applyRecipe(recipeId) {
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.currentMealType,
                    current_date: this.currentDate,
                    recipe_id: recipeId,
                });
                const resp = await fetch('/planner/apply-recipe-option?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeModal();
                await this.loadWeekPlan();
                this.toast.add('Ricetta aggiornata!', 'success');
            } catch (e) {
                this.modalError = 'Errore: ' + e.message;
            }
        },
        closeModal() {
            this.showModal = false;
            this.currentDate = null;
            this.currentMealType = null;
            this.recipeOptions = [];
            this.modalError = null;
        },

        // ── Modal pasto (click su meal-row__info) ─────────────────────────
        openMealModal(dateStr, meal) {
            this.mealModalDate = dateStr;
            this.mealModalMeal = meal;
            this.mealModalComponent = null;
            this.mealModalOptions = [];
            this.mealModalError = null;
            this.mealRecipeDetail = null;
            this.showFreeMealInput = false;
            this.freeMealModalTitle = '';
            this.showMealModal = true;
        },
        async openMealComponent(component) {
            if (!this.profileA || !this.profileB) return;
            this.mealModalComponent = component;
            this.mealModalOptions = [];
            this.mealModalError = null;
            this.mealModalApplying = true;
            try {
                const recipeId = this.mealModalMeal?.items?.[0]?.recipe_id;
                if (!recipeId) throw new Error('Nessuna ricetta associata a questo pasto.');
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                    recipe_id: recipeId,
                    component,
                });
                const resp = await fetch('/planner/change-component?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.mealModalOptions = await resp.json();
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        async applyMealOption(recipeId) {
            if (!this.profileA || !this.profileB) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                    recipe_id: recipeId,
                });
                const resp = await fetch('/planner/apply-recipe-option?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Pasto aggiornato!', 'success');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            }
        },
        openChangeFromMeal() {
            const dateStr = this.mealModalDate;
            const mealType = this.mealModalMeal?.meal_type;
            this.closeMealModal();
            this.openChangeModal(dateStr, mealType);
        },
        async submitCustomMeal() {
            const c = this.customMeal;
            if (!c.title.trim() || !c.protein_name.trim() || !c.carb_name.trim()) {
                this.mealModalError = 'Nome pasto, proteina e carboidrato sono obbligatori.';
                return;
            }
            if (!this.profileA || !this.profileB) return;
            this.mealModalApplying = true;
            this.mealModalError = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const body = {
                    title: c.title.trim(),
                    protein_name: c.protein_name.trim(),
                    protein_grams: c.protein_grams || 0,
                    carb_name: c.carb_name.trim(),
                    carb_grams: c.carb_grams || 0,
                    veg_name: c.veg_name.trim() || null,
                    veg_grams: c.veg_grams || 150,
                    notes: c.notes.trim(),
                };
                const resp = await fetch('/planner/set-custom-meal?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Pasto salvato!', 'success');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        closeMealModal() {
            this.showMealModal = false;
            this.mealModalDate = null;
            this.mealModalMeal = null;
            this.mealModalComponent = null;
            this.mealModalOptions = [];
            this.mealModalError = null;
            this.mealRecipeDetail = null;
            this.showFreeMealInput = false;
            this.freeMealModalTitle = '';
            this.customMeal = { title: '', protein_name: '', protein_grams: 120, carb_name: '', carb_grams: 80, veg_name: '', veg_grams: 150, notes: '' };
        },

        // ── Azioni pasti passati ──────────────────────────────────────────
        async markNotEaten() {
            if (!this.profileA) return;
            this.mealModalApplying = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/not-eaten?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Pasto segnato come non mangiato', 'info');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        async cancelNotEaten() {
            if (!this.profileA) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/not-eaten?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Slot ripristinato', 'info');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            }
        },
        openFreeMealInput() {
            this.showFreeMealInput = true;
            this.freeMealModalTitle = '';
        },
        async confirmFreeMeal() {
            if (!this.profileA) return;
            this.mealModalApplying = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/free-meal?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: this.freeMealModalTitle.trim() || 'Pasto libero', notes: '' }),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('🎉 Pasto libero segnato', 'success');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            } finally {
                this.mealModalApplying = false;
            }
        },
        async cancelFreeMealFromWeek() {
            if (!this.profileA) return;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB?.id || '',
                    meal_type: this.mealModalMeal.meal_type,
                    current_date: this.mealModalDate,
                });
                const resp = await fetch('/planner/free-meal?' + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeMealModal();
                await this.loadWeekPlan();
                this.toast.add('Slot ripristinato', 'info');
            } catch (e) {
                this.mealModalError = 'Errore: ' + e.message;
            }
        },

        // ── Ricetta dettaglio ─────────────────────────────────────────────
        async loadRecipeDetail() {
            const rid = this.mealModalMeal?.items?.[0]?.recipe_id;
            if (!rid) return;
            this.loadingRecipe = true;
            try {
                const r = await fetch(`/recipes/detail/${rid}`);
                this.mealRecipeDetail = r.ok ? await r.json() : null;
                if (!r.ok) this.mealModalError = 'Ricetta non trovata.';
            } catch {
                this.mealRecipeDetail = null;
            } finally {
                this.loadingRecipe = false;
            }
        },

        // ── Utility ──────────────────────────────────────────────────────────
        isPast(dateStr)      { return dateStr < this.today; },
        isFree(meal)         { return meal?.items?.[0]?.food_group === 'free_meal'; },
        isNotEaten(meal)     { return meal?.items?.[0]?.food_group === 'not_eaten'; },
        onStartDateChange() {
            this.weekPlan = null;
            this.error = null;
            this.loadWeekPlan();
        },
        goToToday() {
            const now = new Date();
            const daysToMonday = now.getDay() === 0 ? 6 : now.getDay() - 1;
            const monday = new Date(now);
            monday.setDate(now.getDate() - daysToMonday);
            this.startDate = monday.toISOString().slice(0, 10);
            this.onStartDateChange();
        },
        isToday(dateStr) { return dateStr === this.today; },
        formatDayName(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'long' });
        },
        formatShortDate(dateStr) {
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        },
        formatDateLabel(dateStr) {
            if (!dateStr) return '';
            return new Date(dateStr + 'T12:00:00').toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
        },
    },
});

export default WeekView;
