// planmydinner_addon/frontend/dashboard.js

const Dashboard = {
    template: `
        <div class="dashboard-container">
            <h1>Weekly Plan Dashboard</h1>
            
            <div v-if="loading" class="loading">Loading...</div>
            <div v-else-if="error" class="error">{{ error }}</div>

            <div v-else>
                <!-- TODO: Add profile selectors -->
                <p>Showing plan for: <strong>{{ profileIdA }}</strong> and <strong>{{ profileIdB }}</strong></p>

                <div class="week-view">
                    <div v-if="planLoading" class="loading">Loading weekly plan...</div>
                    <div v-else-if="planError" class="error">{{ planError }}</div>
                    <div v-else v-for="day in weeklyPlan" :key="day.date" class="day-card">
                        <h2>{{ formatDate(day.date) }}</h2>
                        <div class="meals">
                            <div v-for="meal in day.meals" :key="meal.meal_type" class="meal-card">
                                <h3>{{ meal.meal_type }}</h3>
                                <div v-if="meal.items && meal.items.length > 0 && meal.items[0].item_name">
                                    <p>{{ meal.items[0].item_name }}</p>
                                    <button @click="changeRecipe(day.date, meal.meal_type)">Change</button>
                                </div>
                                <div v-else>
                                    <p>No meal planned.</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            weeklyPlan: [],
            loading: true, // Main component loading
            error: null,     // Main component error
            planLoading: false, // Plan-specific loading
            planError: null,    // Plan-specific error
            profileIdA: null, 
            profileIdB: null,
        };
    },
    methods: {
        async fetchProfiles() {
            this.loading = true;
            this.error = null;
            try {
                const response = await fetch(`/profiles/`);
                if (!response.ok) {
                    throw new Error('Failed to fetch profiles.');
                }
                const data = await response.json();
                this.profiles = data;

                if (this.profiles.length >= 2) {
                    this.profileIdA = this.profiles[0].id;
                    this.profileIdB = this.profiles[1].id;
                    await this.fetchWeeklyPlan();
                } else {
                    this.error = "The weekly planner requires at least two user profiles. Please create them in the 'Profiles' page.";
                }

            } catch (err) {
                this.error = err.message;
            } finally {
                this.loading = false;
            }
        },
        async fetchWeeklyPlan() {
            if (!this.profileIdA || !this.profileIdB) {
                this.planError = "Profile IDs are not set.";
                return;
            }
            this.planLoading = true;
            this.planError = null;
            try {
                // The prefix /api is handled by the addon ingress
                const response = await fetch(`/planner/weekly-plan?profile_id_A=${this.profileIdA}&profile_id_B=${this.profileIdB}`);
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to fetch weekly plan.');
                }
                this.weeklyPlan = await response.json();
            } catch (err) {
                this.planError = err.message;
            } finally {
                this.planLoading = false;
            }
        },
        formatDate(dateString) {
            const options = { weekday: 'long', month: 'long', day: 'numeric' };
            return new Date(dateString).toLocaleDateString(undefined, options);
        },
        changeRecipe(date, mealType) {
            // Placeholder for Step 3
            alert(`Change recipe for ${mealType} on ${date}`);
        }
    },
    mounted() {
        this.fetchProfiles();
    }
};

export default Dashboard;
