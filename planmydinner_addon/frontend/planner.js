import { defineComponent } from 'vue';

const WeekView = defineComponent({
    name: 'WeekView',
    inject: ['toast'],
    template: `
        <div class="week-view">
            <div class="week-controls">
                <h2>Settimana</h2>
                <div class="date-picker-row">
                    <label>Dal</label>
                    <input type="date" v-model="startDate" @change="onStartDateChange" />
                    <span class="date-range-label">→ {{ endDateLabel }}</span>
                    <button @click="goToToday" class="btn-today">Oggi</button>
                </div>
            </div>

            <div v-if="loading" class="loading">Caricamento...</div>
            <div v-if="error" class="error-box">{{ error }}</div>
            <div v-if="!loading && profiles.length < 2" class="hint">
                Crea almeno 2 profili per usare il pianificatore.
            </div>

            <div v-if="!loading && profiles.length >= 2 && !weekPlan && !error" class="no-plan">
                <p>Nessun piano per questo range.</p>
                <button @click="generateWeek" :disabled="generating" class="btn-primary">
                    {{ generating ? 'Generazione...' : 'Genera piano 7 giorni' }}
                </button>
            </div>

            <div v-if="weekPlan" class="week-actions">
                <button @click="generateWeek" :disabled="generating" class="btn-regenerate">
                    {{ generating ? 'Rigenerando...' : 'Rigenera' }}
                </button>
            </div>

            <div v-if="weekPlan" class="week-grid">
                <div v-for="day in weekPlan" :key="day.date" class="day-card">
                    <div class="day-header">
                        <span class="day-name">{{ formatDayName(day.date) }}</span>
                        <span class="day-date">{{ formatShortDate(day.date) }}</span>
                        <span v-if="isToday(day.date)" class="today-badge">Oggi</span>
                    </div>
                    <div v-if="day.meals && day.meals.length > 0">
                        <div v-for="meal in day.meals" :key="meal.meal_type" class="week-meal">
                            <span class="meal-type-label">{{ meal.meal_type === 'pranzo' ? '☀️' : '🌙' }}</span>
                            <span class="meal-name">{{ meal.items?.[0]?.item_name || '—' }}</span>
                            <button @click.stop="openChangeModal(day.date, meal.meal_type)"
                                    class="btn-week-change" title="Cambia ricetta">↺</button>
                        </div>
                    </div>
                    <div v-else class="no-meals">Nessun pasto</div>
                </div>
            </div>

            <!-- Modal cambio ricetta -->
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
        const today = new Date().toISOString().slice(0, 10);
        return {
            profiles: [],
            startDate: today,
            weekPlan: null,
            loading: false,
            error: null,
            generating: false,
            today,
            // Modal state
            showModal: false,
            currentDate: null,
            currentMealType: null,
            recipeOptions: [],
            loadingOptions: false,
            modalError: null,
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
    },
    mounted() {
        this.loadData();
    },
    methods: {
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const resp = await fetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) {
                    await this.loadWeekPlan();
                }
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
        async generateWeek() {
            if (!this.profileA || !this.profileB) return;
            this.generating = true;
            this.error = null;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    current_date: this.startDate,
                });
                const resp = await fetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.weekPlan = await resp.json();
                this.toast.add('Piano generato!', 'success');
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            } finally {
                this.generating = false;
            }
        },
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
        onStartDateChange() {
            this.weekPlan = null;
            this.error = null;
            this.loadWeekPlan();
        },
        goToToday() {
            this.startDate = this.today;
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
