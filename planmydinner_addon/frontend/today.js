import { defineComponent } from 'vue';

const TodayView = defineComponent({
    name: 'TodayView',
    template: `
        <div class="today-view">
            <h2>Oggi — {{ formattedDate }}</h2>

            <div v-if="loading" class="loading">Caricamento...</div>
            <div v-if="error" class="error">{{ error }}</div>

            <div v-if="!loading && !error && !todayPlan && profiles.length >= 2">
                <p>Nessun piano trovato per questa settimana.</p>
                <button @click="generateWeek" :disabled="generating">
                    {{ generating ? 'Generazione...' : 'Genera piano questa settimana' }}
                </button>
            </div>

            <div v-if="!loading && !error && !todayPlan && profiles.length < 2">
                <p>Crea almeno 2 profili nella sezione Profili per usare il pianificatore.</p>
            </div>

            <div v-if="todayPlan">
                <div v-for="meal in todayPlan.meals" :key="meal.meal_type" class="meal-box">
                    <h3>{{ meal.meal_type === 'pranzo' ? 'Pranzo' : 'Cena' }}</h3>
                    <div v-if="meal.items && meal.items.length > 0" class="recipe-name">
                        {{ meal.items[0].item_name }}
                    </div>
                    <div v-else class="recipe-name empty">Nessuna ricetta assegnata</div>
                    <div class="meal-actions">
                        <button @click="openChangeModal(meal.meal_type)">Cambia</button>
                        <button @click="markConsumed(meal.meal_type)" class="btn-consumed">Ho mangiato</button>
                    </div>
                </div>
            </div>

            <!-- Modal cambio ricetta -->
            <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
                <div class="modal">
                    <h3>Scegli una ricetta per {{ currentMealType === 'pranzo' ? 'pranzo' : 'cena' }}</h3>
                    <div v-if="loadingOptions" class="loading">Caricamento opzioni...</div>
                    <div v-if="modalError" class="error">{{ modalError }}</div>
                    <div v-for="option in recipeOptions" :key="option.option_id" class="recipe-option"
                         @click="applyRecipe(option.recipe_id)">
                        <strong>{{ option.name }}</strong>
                        <span>{{ option.total_time_minutes }} min · {{ option.difficulty }}</span>
                        <span v-if="option.key_ingredients.length">🥗 {{ option.key_ingredients.join(', ') }}</span>
                    </div>
                    <button @click="closeModal" class="btn-secondary">Annulla</button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            dailyPlans: [],
            todayPlan: null,
            loading: false,
            error: null,
            generating: false,
            showModal: false,
            currentMealType: null,
            recipeOptions: [],
            loadingOptions: false,
            modalError: null,
            today: new Date().toISOString().slice(0, 10),
        };
    },
    computed: {
        formattedDate() {
            const d = new Date(this.today + 'T12:00:00');
            return d.toLocaleDateString('it-IT', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
        },
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
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) {
                    await this.loadWeeklyPlan();
                }
            } catch (e) {
                this.error = 'Errore nel caricamento dei profili: ' + e.message;
            } finally {
                this.loading = false;
            }
        },
        async loadWeeklyPlan() {
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB.id,
                start_date: this.today,
            });
            const resp = await fetch('/planner/weekly-plan?' + params);
            if (!resp.ok) {
                this.dailyPlans = [];
                this.todayPlan = null;
                return;
            }
            this.dailyPlans = await resp.json();
            this.todayPlan = this.dailyPlans.find(d => d.date === this.today) || null;
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
                const resp = await fetch('/planner/generate-week?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.dailyPlans = await resp.json();
                this.todayPlan = this.dailyPlans.find(d => d.date === this.today) || null;
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
                const params = new URLSearchParams({
                    profile_id_A: this.profileA.id,
                    profile_id_B: this.profileB.id,
                    meal_type: mealType,
                    current_date: this.today,
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
                    current_date: this.today,
                    recipe_id: recipeId,
                });
                const resp = await fetch('/planner/apply-recipe-option?' + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.closeModal();
                await this.loadWeeklyPlan();
            } catch (e) {
                this.modalError = 'Errore nell\'applicazione della ricetta: ' + e.message;
            }
        },
        async markConsumed(mealType) {
            if (!this.profileA) return;
            try {
                const meal = this.todayPlan?.meals.find(m => m.meal_type === mealType);
                const recipeId = meal?.items?.[0]?.item_name ? null : null;
                const body = {
                    profile_id: this.profileA.id,
                    date: this.today,
                    meal_type: mealType,
                    type: 'planned',
                    consumed_recipe_id: recipeId,
                };
                await fetch('/consumed-entries/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                alert('Pasto registrato come consumato!');
            } catch (e) {
                alert('Errore: ' + e.message);
            }
        },
        closeModal() {
            this.showModal = false;
            this.currentMealType = null;
            this.recipeOptions = [];
            this.modalError = null;
        },
    },
});

export default TodayView;
