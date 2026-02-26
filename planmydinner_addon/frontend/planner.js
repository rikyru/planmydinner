import { defineComponent } from 'vue';

const Planner = defineComponent({
    template: `
        <div>
            <h2>Meal Planner</h2>

            <div class="controls">
                <select v-model="selectedProfile">
                    <option :value="null" disabled>Select a profile</option>
                    <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
                        {{ profile.name }} ({{ profile.id }})
                    </option>
                </select>
                <input type="date" v-model="selectedDate">
                <button @click="fetchPlan" :disabled="!selectedProfile">Fetch Plan</button>
            </div>

            <div v-if="loading" class="loading">Loading...</div>
            <div v-if="error" class="error">{{ error }}</div>

            <div v-if="plan" class="plan-view">
                <h3>Plan for {{ plan.profile_id }} starting on {{ plan.start_date }}</h3>
                <div v-for="day in plan.daily_plans" :key="day.date" class="daily-plan-section">
                    <h4>{{ day.date }}</h4>
                    <div v-for="meal in day.meals" :key="meal.meal_type" class="meal-section">
                        <h5>{{ meal.meal_type }}</h5>
                        <table>
                            <thead>
                                <tr>
                                    <th>Item</th>
                                    <th>Quantity</th>
                                    <th>Unit</th>
                                    <th>Food Group</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(item, itemIndex) in meal.items" :key="itemIndex">
                                    <td>{{ item.item_name }}</td>
                                    <td>{{ item.quantity }}</td>
                                    <td>{{ item.unit }}</td>
                                    <td>{{ item.food_group }}</td>
                                </tr>
                                <tr v-if="!meal.items.length">
                                    <td colspan="4">No items planned for this meal.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            <div v-if="!plan && !loading && !error">
                <p>Select a profile and date, then click "Fetch Plan" to see a saved meal plan.</p>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            selectedProfile: null,
            selectedDate: new Date().toISOString().slice(0, 10),
            plan: null,
            loading: false,
            error: null,
        };
    },
    mounted() {
        this.fetchProfiles();
    },
    methods: {
        fetchProfiles() {
            fetch('/profiles')
                .then(response => response.json())
                .then(data => {
                    this.profiles = data;
                })
                .catch(error => console.error('Error fetching profiles:', error));
        },
        fetchPlan() {
            if (!this.selectedProfile) return;

            this.loading = true;
            this.error = null;
            this.plan = null;

            const url = new URL('/planner/plan', window.location.origin);
            url.searchParams.append('profile_id', this.selectedProfile);
            url.searchParams.append('plan_date', this.selectedDate);

            fetch(url)
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(err => { throw new Error(err.detail || 'Failed to fetch plan') });
                    }
                    return response.json();
                })
                .then(data => {
                    this.plan = data;
                })
                .catch(error => {
                    this.error = 'Error: ' + error.message;
                    console.error('Error fetching plan:', error);
                })
                .finally(() => {
                    this.loading = false;
                });
        },
    },
});

export default Planner;
