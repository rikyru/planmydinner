import { defineComponent } from 'vue';

const Dashboard = defineComponent({
    name: 'Dashboard',
    inject: ['toast'],
    template: `
        <div class="dashboard-container">
            <div class="dashboard-header">
                <h1>Piano della Settimana</h1>
                <button class="btn-primary" @click="generateWeek" :disabled="generating || loading">
                    {{ generating ? 'Generazione...' : '🔄 Genera settimana' }}
                </button>
            </div>

            <div v-if="loading" class="loading">Caricamento piano...</div>
            <div v-else-if="error" class="error-box">{{ error }}</div>

            <div v-else-if="profiles.length < 2" class="empty-box">
                <p>Servono almeno 2 profili per usare il pianificatore.</p>
                <p style="font-size:13px;">Crea i profili nella sezione <strong>Profili</strong>.</p>
            </div>

            <div v-else-if="weeklyPlan.length === 0" class="empty-box">
                <p>Nessun piano generato per questa settimana.</p>
                <button class="btn-primary" @click="generateWeek" :disabled="generating">
                    {{ generating ? 'Generazione...' : 'Genera piano ora' }}
                </button>
            </div>

            <div v-else>
                <p class="plan-subtitle">
                    Piano per <strong>{{ profileA?.name }}</strong> e <strong>{{ profileB?.name }}</strong>
                </p>
                <div class="week-view">
                    <div v-for="day in weeklyPlan" :key="day.date" class="day-card">
                        <h2 class="day-title">{{ formatDate(day.date) }}</h2>
                        <div class="meals">
                            <div v-for="meal in day.meals" :key="meal.meal_type" class="meal-card">
                                <div class="meal-header">
                                    <span class="meal-type">{{ meal.meal_type === 'pranzo' ? '☀️ Pranzo' : '🌙 Cena' }}</span>
                                    <button class="btn-change" @click="openChangeModal(day.date, meal.meal_type)">Cambia</button>
                                </div>
                                <div v-if="meal.items && meal.items.length > 0 && meal.items[0].item_name" class="recipe-name">
                                    {{ meal.items[0].item_name }}
                                </div>
                                <div v-else class="recipe-name empty-meal">
                                    Nessuna ricetta assegnata
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Modal cambio ricetta -->
            <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
                <div class="modal">
                    <h3>Cambia ricetta — {{ currentMealType === 'pranzo' ? 'Pranzo' : 'Cena' }} {{ formatDateShort(currentDate) }}</h3>
                    <div v-if="loadingOptions" class="loading">Caricamento opzioni...</div>
                    <div v-else-if="modalError" class="error-box">{{ modalError }}</div>
                    <div v-else-if="recipeOptions.length === 0" class="empty-box" style="padding:16px">
                        <p>Nessuna alternativa trovata per questo pasto.</p>
                    </div>
                    <div v-else class="recipe-options">
                        <div v-for="option in recipeOptions" :key="option.option_id"
                             class="recipe-option" @click="applyRecipe(option.recipe_id)">
                            <div class="option-name">{{ option.name }}</div>
                            <div class="option-meta">
                                ⏱ {{ option.total_time_minutes }} min &nbsp;·&nbsp;
                                {{ option.difficulty }}
                                <span v-if="option.key_ingredients.length">
                                    &nbsp;·&nbsp; {{ option.key_ingredients.join(', ') }}
                                </span>
                            </div>
                        </div>
                    </div>
                    <button class="btn-secondary" style="margin-top:12px" @click="closeModal">Annulla</button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            weeklyPlan: [],
            loading: true,
            error: null,
            generating: false,
            showModal: false,
            currentDate: null,
            currentMealType: null,
            recipeOptions: [],
            loadingOptions: false,
            modalError: null,
            today: new Date().toISOString().slice(0, 10),
        };
    },
    computed: {
        profileA() { return this.profiles[0] || null; },
        profileB() { return this.profiles[1] || null; },
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
                if (!resp.ok) throw new Error('Errore nel caricamento dei profili.');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) {
                    await this.fetchWeeklyPlan();
                }
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        async fetchWeeklyPlan() {
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB.id,
                start_date: this.today,
            });
            const resp = await fetch('/planner/weekly-plan?' + params);
            if (!resp.ok) {
                this.weeklyPlan = [];
                return;
            }
            this.weeklyPlan = await resp.json();
        },
        async generateWeek() {
            if (!this.profileA || !this.profileB) return;
            this.generating = true;
            try {
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    current_date: this.today,
                });
                const resp = await fetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) {
                    const data = await resp.json();
                    throw new Error(data.detail || 'Errore nella generazione.');
                }
                this.weeklyPlan = await resp.json();
                this.toast.add('Piano settimanale generato!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.generating = false;
            }
        },
        async openChangeModal(date, mealType) {
            this.currentDate = date;
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
                    current_date: date,
                });
                const resp = await fetch('/planner/change-recipe?' + params, { method: 'POST' });
                if (!resp.ok) {
                    const data = await resp.json();
                    throw new Error(data.detail || 'Nessuna alternativa trovata.');
                }
                this.recipeOptions = await resp.json();
            } catch (e) {
                this.modalError = e.message;
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
                if (!resp.ok) throw new Error('Errore nell\'applicazione della ricetta.');
                this.closeModal();
                await this.fetchWeeklyPlan();
                this.toast.add('Ricetta aggiornata!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        closeModal() {
            this.showModal = false;
            this.currentDate = null;
            this.currentMealType = null;
            this.recipeOptions = [];
            this.modalError = null;
        },
        formatDate(dateString) {
            const d = new Date(dateString + 'T12:00:00');
            return d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
        },
        formatDateShort(dateString) {
            if (!dateString) return '';
            const d = new Date(dateString + 'T12:00:00');
            return d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        },
    },
});

export default Dashboard;
