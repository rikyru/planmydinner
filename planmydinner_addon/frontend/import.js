import { defineComponent } from 'vue';

const ImportWizard = defineComponent({
    template: `
        <div>
            <h2>Import Wizard</h2>

            <div class="tab-bar" v-if="!parsedData">
                <button @click="activeTab = 'pdf'" :class="{active: activeTab === 'pdf'}">PDF</button>
                <button @click="activeTab = 'text'" :class="{active: activeTab === 'text'}">Testo</button>
            </div>

            <div v-if="!parsedData">
                <select v-model="selectedProfile">
                    <option :value="null" disabled>Seleziona un profilo</option>
                    <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
                        {{ profile.name }} ({{ profile.id }})
                    </option>
                </select>

                <!-- PDF tab -->
                <div v-if="activeTab === 'pdf'">
                    <input type="file" @change="onFileChange" accept=".pdf">
                    <button @click="uploadPdf" :disabled="!file || !selectedProfile">Carica PDF</button>
                </div>

                <!-- Text tab -->
                <div v-if="activeTab === 'text'">
                    <textarea v-model="textContent" rows="10" placeholder="Incolla qui il tuo piano settimanale in formato testo..."></textarea>
                    <button @click="uploadText" :disabled="!textContent || !selectedProfile">Importa testo</button>
                </div>

                <div v-if="uploadError" class="error">{{ uploadError }}</div>
            </div>

            <div v-if="parsedData">
                <h3>Rivedi e modifica il piano per: {{ parsedData.profile_id }}</h3>
                <div v-for="day in parsedData.daily_plans" :key="day.date" class="daily-plan-section">
                    <h4>{{ day.date }}</h4>
                    <div v-for="meal in day.meals" :key="meal.meal_type" class="meal-section">
                        <h5>{{ meal.meal_type }}</h5>
                        <table>
                            <thead>
                                <tr>
                                    <th>Alimento</th>
                                    <th>Quantità</th>
                                    <th>Unità</th>
                                    <th>Gruppo</th>
                                    <th>Stimato</th>
                                    <th>Alternative</th>
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
                                    <td colspan="6">Nessun alimento per questo pasto.</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div class="rules-section">
                    <h4>Regole di rotazione</h4>
                    <ul>
                        <li v-for="(rule, index) in parsedData.rotation_rules" :key="index">
                            {{ rule.food_group_or_item }}: Max {{ rule.max_per_week || 'N/A' }} / Min {{ rule.min_per_week || 'N/A' }} a settimana (Hard: {{ rule.is_hard_constraint }})
                        </li>
                    </ul>
                </div>

                <div class="cooking-methods-section">
                    <h4>Metodi di cottura consentiti</h4>
                    <ul>
                        <li v-for="(method, index) in parsedData.allowed_cooking_methods" :key="index">
                            {{ method }}
                        </li>
                    </ul>
                </div>

                <button @click="save">Salva</button>
                <button @click="cancel" class="btn-secondary">Annulla</button>
            </div>
        </div>
    `,
    data() {
        return {
            activeTab: 'pdf',
            file: null,
            textContent: '',
            parsedData: null,
            profiles: [],
            selectedProfile: null,
            uploadError: null,
        }
    },
    mounted() {
        this.fetchProfiles();
    },
    methods: {
        fetchProfiles() {
            fetch('/profiles/')
                .then(response => response.json())
                .then(data => { this.profiles = data; });
        },
        onFileChange(e) {
            this.file = e.target.files[0];
        },
        uploadPdf() {
            this.uploadError = null;
            const formData = new FormData();
            formData.append('pdf_file', this.file);
            formData.append('profile_id', this.selectedProfile);

            fetch('/import/pdf', { method: 'POST', body: formData })
                .then(response => {
                    if (!response.ok) return response.json().then(e => { throw new Error(e.detail || 'Errore'); });
                    return response.json();
                })
                .then(data => { this.parsedData = data; })
                .catch(e => { this.uploadError = e.message; });
        },
        uploadText() {
            this.uploadError = null;
            const formData = new FormData();
            formData.append('profile_id', this.selectedProfile);
            formData.append('text_content', this.textContent);

            fetch('/import/text', { method: 'POST', body: formData })
                .then(response => {
                    if (!response.ok) return response.json().then(e => { throw new Error(e.detail || 'Errore'); });
                    return response.json();
                })
                .then(data => { this.parsedData = data; })
                .catch(e => { this.uploadError = e.message; });
        },
        save() {
            if (this.parsedData && this.parsedData.daily_plans) {
                this.parsedData.daily_plans.forEach(day => {
                    day.meals.forEach(meal => {
                        meal.items.forEach(item => {
                            if (typeof item.alternatives === 'string') {
                                item.alternatives = item.alternatives.split(',').map(a => a.trim()).filter(a => a.length > 0);
                            }
                        });
                    });
                });
            }

            fetch('/import/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.parsedData),
            }).then(() => { this.cancel(); });
        },
        cancel() {
            this.parsedData = null;
            this.file = null;
            this.textContent = '';
            this.selectedProfile = null;
            this.uploadError = null;
        },
        updateAlternatives(item) {
            if (typeof item.alternatives === 'string') {
                item.alternatives = item.alternatives.split(',').map(a => a.trim()).filter(a => a.length > 0);
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
