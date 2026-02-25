import { defineComponent } from 'vue';

const ImportWizard = defineComponent({
    template: `
        <div>
            <h2>Import Wizard</h2>
            <div v-if="!parsedData">
                <select v-model="selectedProfile">
                    <option :value="null" disabled>Select a profile</option>
                    <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
                        {{ profile.name }} ({{ profile.id }})
                    </option>
                </select>
                <input type="file" @change="onFileChange">
                <button @click="upload" :disabled="!file || !selectedProfile">Upload</button>
            </div>
            <div v-if="parsedData">
                <h3>Review and Edit Meal Plan for Profile: {{ parsedData.profile_id }}</h3>
                <div v-for="day in parsedData.daily_plans" :key="day.date" class="daily-plan-section">
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
                                    <th>Estimated</th>
                                    <th>Alternatives</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(item, itemIndex) in meal.items" :key="itemIndex">
                                    <td><input v-model="item.item_name" class="item-name-input"></td>
                                    <td><input v-model="item.quantity" type="number" class="quantity-input" :class="{'estimated-unit': item.is_estimated_unit}"></td>
                                    <td><input v-model="item.unit" class="unit-input" :class="{'estimated-unit': item.is_estimated_unit}"></td>
                                    <td><input v-model="item.food_group" class="food-group-input"></td>
                                    <td><input type="checkbox" v-model="item.is_estimated_unit" disabled></td>
                                    <td><input v-model="item.alternatives" @change="updateAlternatives(item)" class="alternatives-input"></td>
                                </tr>
                                <tr v-if="!meal.items.length">
                                    <td colspan="5">No items planned for this meal.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <div class="rules-section">
                    <h4>Rotation Rules</h4>
                    <ul>
                        <li v-for="(rule, index) in parsedData.rotation_rules" :key="index">
                            {{ rule.food_group_or_item }}: Max {{ rule.max_per_week || 'N/A' }} / Min {{ rule.min_per_week || 'N/A' }} per week (Hard: {{ rule.is_hard_constraint }})
                        </li>
                    </ul>
                </div>

                <div class="cooking-methods-section">
                    <h4>Allowed Cooking Methods</h4>
                    <ul>
                        <li v-for="(method, index) in parsedData.allowed_cooking_methods" :key="index">
                            {{ method }}
                        </li>
                    </ul>
                </div>

                <button @click="save">Save</button>
                <button @click="cancel">Cancel</button>
            </div>
        </div>
    `,
    data() {
        return {
            file: null,
            parsedData: null,
            profiles: [],
            selectedProfile: null,
        }
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
                });
        },
        onFileChange(e) {
            this.file = e.target.files[0];
        },
        upload() {
            const formData = new FormData();
            formData.append('pdf_file', this.file);
            formData.append('profile_id', this.selectedProfile);

            fetch('/import/pdf', {
                method: 'POST',
                body: formData,
            })
            .then(response => response.json())
            .then(data => {
                this.parsedData = data;
            });
        },
        save() {
            // Convert alternatives back to array of strings before saving
            if (this.parsedData && this.parsedData.daily_plans) {
                this.parsedData.daily_plans.forEach(day => {
                    day.meals.forEach(meal => {
                        meal.items.forEach(item => {
                            if (typeof item.alternatives === 'string') {
                                item.alternatives = item.alternatives.split(',').map(alt => alt.trim()).filter(alt => alt.length > 0);
                            }
                        });
                    });
                });
            }

            fetch('/import/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.parsedData),
            })
            .then(() => {
                this.cancel();
            });
        },
        cancel() {
            this.parsedData = null;
            this.file = null;
            this.selectedProfile = null;
        },
        updateAlternatives(item) {
            if (typeof item.alternatives === 'string') {
                item.alternatives = item.alternatives.split(',').map(alt => alt.trim()).filter(alt => alt.length > 0);
            }
        },
        initializeAlternatives() {
            if (this.parsedData && this.parsedData.daily_plans) {
                this.parsedData.daily_plans.forEach(day => {
                    day.meals.forEach(meal => {
                        meal.items.forEach(item => {
                            if (Array.isArray(item.alternatives)) {
                                item.alternatives = item.alternatives.join(', ');
                            }
                        });
                    });
                });
            }
        }
    },
    watch: {
        parsedData: {
            handler: 'initializeAlternatives',
            immediate: true,
            deep: true
        }
    }
});

export default ImportWizard;
