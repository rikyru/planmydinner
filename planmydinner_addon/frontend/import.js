import { defineComponent } from 'vue';

const ImportWizard = defineComponent({
    name: 'ImportWizard',
    inject: ['toast'],
    template: `
        <div class="import-view">
            <h2>Importa Piano Alimentare</h2>

            <div v-if="!parsedData">
                <div class="tab-bar">
                    <button @click="activeTab = 'pdf'" :class="{active: activeTab === 'pdf'}">PDF</button>
                    <button @click="activeTab = 'text'" :class="{active: activeTab === 'text'}">Testo</button>
                </div>

                <div class="import-form">
                    <label>Profilo</label>
                    <select v-model="selectedProfile">
                        <option :value="null" disabled>Seleziona un profilo...</option>
                        <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
                            {{ profile.name }}
                        </option>
                    </select>

                    <!-- PDF tab -->
                    <div v-if="activeTab === 'pdf'" class="tab-panel">
                        <p class="hint">Carica il PDF del tuo nutrizionista. Il testo verrà estratto e analizzato dall'IA.</p>
                        <input type="file" @change="onFileChange" accept=".pdf">
                        <button class="btn-primary" @click="uploadPdf" :disabled="!file || !selectedProfile || uploading">
                            {{ uploading ? 'Analisi in corso...' : 'Carica e analizza PDF' }}
                        </button>
                    </div>

                    <!-- Text tab -->
                    <div v-if="activeTab === 'text'" class="tab-panel">
                        <p class="hint">Incolla il testo del piano alimentare (copia dal PDF o scrivi manualmente).</p>
                        <textarea v-model="textContent" rows="12" placeholder="Lunedì&#10;Pranzo: pasta al pomodoro 80g, insalata mista&#10;Cena: pollo alla griglia 150g, verdure grigliate&#10;..."></textarea>
                        <button class="btn-primary" @click="uploadText" :disabled="!textContent || !selectedProfile || uploading">
                            {{ uploading ? 'Analisi in corso...' : 'Importa testo' }}
                        </button>
                    </div>

                    <div v-if="uploading" class="loading">L'IA sta analizzando il piano, potrebbero volerci alcuni secondi...</div>
                    <div v-if="uploadError" class="error-box">
                        {{ uploadError }}
                        <div v-if="activeTab === 'pdf'" style="margin-top:8px; font-size:13px;">
                            Suggerimento: prova a copiare il testo dal PDF e usa la tab <strong>Testo</strong>.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Preview piano parsato -->
            <div v-if="parsedData">
                <div class="preview-header">
                    <h3>Rivedi il piano — {{ parsedData.profile_id }}</h3>
                    <p style="color:#868e96; font-size:13px;">Verifica i dati estratti e modificali se necessario prima di salvare.</p>
                </div>

                <div v-for="day in parsedData.daily_plans" :key="day.date" class="day-preview">
                    <h4 class="day-preview-title">{{ formatDate(day.date) }}</h4>
                    <div v-for="meal in day.meals" :key="meal.meal_type" class="meal-preview">
                        <h5>{{ meal.meal_type === 'pranzo' ? '☀️ Pranzo' : '🌙 Cena' }}</h5>
                        <div v-if="meal.items.length === 0" style="color:#adb5bd; font-size:13px;">Nessun alimento</div>
                        <table v-else class="items-table">
                            <thead>
                                <tr>
                                    <th>Alimento</th>
                                    <th>Qtà</th>
                                    <th>Unità</th>
                                    <th>Gruppo</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(item, idx) in meal.items" :key="idx">
                                    <td><input v-model="item.item_name" class="item-input"></td>
                                    <td><input v-model.number="item.quantity" type="number" class="qty-input"></td>
                                    <td><input v-model="item.unit" class="unit-input"></td>
                                    <td><input v-model="item.food_group" class="group-input"></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <div v-if="parsedData.rotation_rules && parsedData.rotation_rules.length" class="rules-preview">
                    <h4>Regole di rotazione</h4>
                    <ul>
                        <li v-for="(rule, i) in parsedData.rotation_rules" :key="i">
                            {{ rule.food_group_or_item }}: max {{ rule.max_per_week || '—' }} / min {{ rule.min_per_week || '—' }} a settimana
                        </li>
                    </ul>
                </div>

                <div class="preview-actions">
                    <button class="btn-primary" @click="save" :disabled="saving">
                        {{ saving ? 'Salvataggio...' : 'Salva piano' }}
                    </button>
                    <button class="btn-secondary" @click="cancel">Annulla</button>
                </div>
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
            uploading: false,
            saving: false,
            uploadError: null,
        };
    },
    mounted() {
        this.fetchProfiles();
    },
    methods: {
        async fetchProfiles() {
            try {
                const resp = await fetch('/profiles/');
                if (resp.ok) this.profiles = await resp.json();
            } catch (e) {
                // silenzioso
            }
        },
        onFileChange(e) {
            this.file = e.target.files[0] || null;
            this.uploadError = null;
        },
        async uploadPdf() {
            this.uploadError = null;
            this.uploading = true;
            try {
                const formData = new FormData();
                formData.append('pdf_file', this.file);
                formData.append('profile_id', this.selectedProfile);

                const resp = await fetch('/import/pdf', { method: 'POST', body: formData });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ detail: 'Errore sconosciuto' }));
                    throw new Error(err.detail || 'Errore nel parsing del PDF');
                }
                this.parsedData = await resp.json();
                this._initAlternatives();
            } catch (e) {
                this.uploadError = e.message;
            } finally {
                this.uploading = false;
            }
        },
        async uploadText() {
            this.uploadError = null;
            this.uploading = true;
            try {
                const formData = new FormData();
                formData.append('profile_id', this.selectedProfile);
                formData.append('text_content', this.textContent);

                const resp = await fetch('/import/text', { method: 'POST', body: formData });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({ detail: 'Errore sconosciuto' }));
                    throw new Error(err.detail || 'Errore nell\'analisi del testo');
                }
                this.parsedData = await resp.json();
                this._initAlternatives();
            } catch (e) {
                this.uploadError = e.message;
            } finally {
                this.uploading = false;
            }
        },
        async save() {
            this._serializeAlternatives();
            this.saving = true;
            try {
                const resp = await fetch('/import/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.parsedData),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio del piano');
                this.toast.add('Piano salvato con successo!', 'success');
                this.cancel();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.saving = false;
            }
        },
        cancel() {
            this.parsedData = null;
            this.file = null;
            this.textContent = '';
            this.selectedProfile = null;
            this.uploadError = null;
        },
        formatDate(dateString) {
            const d = new Date(dateString + 'T12:00:00');
            return d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
        },
        _initAlternatives() {
            if (!this.parsedData?.daily_plans) return;
            for (const day of this.parsedData.daily_plans) {
                for (const meal of day.meals) {
                    for (const item of meal.items) {
                        if (Array.isArray(item.alternatives)) {
                            item.alternatives = item.alternatives.join(', ');
                        }
                    }
                }
            }
        },
        _serializeAlternatives() {
            if (!this.parsedData?.daily_plans) return;
            for (const day of this.parsedData.daily_plans) {
                for (const meal of day.meals) {
                    for (const item of meal.items) {
                        if (typeof item.alternatives === 'string') {
                            item.alternatives = item.alternatives.split(',').map(a => a.trim()).filter(Boolean);
                        }
                    }
                }
            }
        },
    },
});

export default ImportWizard;
