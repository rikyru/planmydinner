import { defineComponent } from 'vue';

const Profiles = defineComponent({
    name: 'Profiles',
    inject: ['toast'],
    template: `
        <div class="profiles-view">
            <h2>Profili</h2>

            <!-- Crea profilo -->
            <div class="card create-profile">
                <h3>Nuovo profilo</h3>
                <div class="form-row">
                    <input v-model="newProfileId" placeholder="ID (es. riccardo)" />
                    <input v-model="newProfileName" placeholder="Nome (es. Riccardo)" />
                    <button @click="createProfile" :disabled="!newProfileId || !newProfileName">Crea</button>
                </div>
            </div>

            <!-- Lista profili -->
            <div class="card profile-list">
                <h3>Profili esistenti</h3>
                <ul v-if="profiles.length">
                    <li v-for="p in profiles" :key="p.id" class="profile-item"
                        @click="selectProfile(p)" :class="{ active: selectedProfile?.id === p.id }">
                        <strong>{{ p.name }}</strong>
                        <span class="profile-id">{{ p.id }}</span>
                    </li>
                </ul>
                <p v-else class="hint">Nessun profilo. Creane uno sopra.</p>
            </div>

            <!-- Regole del Piano per il profilo selezionato -->
            <div v-if="selectedProfile" class="card rules-panel">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
                    <h3 style="margin:0">Regole del Piano — {{ selectedProfile.name }}</h3>
                    <button v-if="rules && !editingRules" @click="startEditRules" class="btn-secondary" style="font-size:13px;">
                        ✏️ Modifica vincoli
                    </button>
                </div>

                <div v-if="loadingRules" class="loading">Caricamento regole...</div>

                <!-- MODALITÀ VISUALIZZAZIONE -->
                <div v-else-if="!editingRules">
                    <div v-if="!rules">
                        <p class="hint">Nessun piano attivo trovato per questo profilo.<br>
                        Importa un piano nella sezione <em>Importa</em> per vedere le regole,
                        oppure <button @click="startEditRules" class="btn-secondary" style="font-size:12px;padding:4px 10px;">crea i vincoli manualmente</button>.</p>
                    </div>
                    <div v-else>
                        <!-- PlanRules: grammature target (se disponibili) -->
                        <div v-if="rules.plan_rules" class="rules-section">
                            <h4>Grammi target</h4>
                            <table class="rules-table">
                                <thead>
                                    <tr>
                                        <th>Pasto</th>
                                        <th>Carboidrati (g)</th>
                                        <th>Proteine (g)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="mt in ['pranzo','cena']" :key="mt">
                                        <td>{{ mt === 'pranzo' ? 'Pranzo' : 'Cena' }}</td>
                                        <td>{{ rules.plan_rules.carb_target?.[mt] ?? '—' }}</td>
                                        <td>{{ rules.plan_rules.protein_target?.[mt] ?? '—' }}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <!-- PlanRules: frequenze settimanali -->
                        <div v-if="rules.plan_rules && rules.plan_rules.frequency_targets" class="rules-section">
                            <h4>Frequenze settimanali</h4>
                            <table class="rules-table">
                                <thead>
                                    <tr>
                                        <th>Categoria proteica</th>
                                        <th>Min / sett.</th>
                                        <th>Max / sett.</th>
                                        <th>Max rigido</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="(ft, cat) in rules.plan_rules.frequency_targets" :key="cat">
                                        <td>{{ cat }}</td>
                                        <td>{{ ft.min ?? '—' }}</td>
                                        <td>{{ ft.max ?? '—' }}</td>
                                        <td>
                                            <span v-if="ft.hard_max != null" class="badge-hard">{{ ft.hard_max }}</span>
                                            <span v-else class="badge-soft">—</span>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <!-- Fallback: rotation_rules legacy -->
                        <div v-else-if="rules.rotation_rules && rules.rotation_rules.length" class="rules-section">
                            <h4>Frequenze settimanali</h4>
                            <table class="rules-table">
                                <thead>
                                    <tr>
                                        <th>Alimento / Gruppo</th>
                                        <th>Min / sett.</th>
                                        <th>Max / sett.</th>
                                        <th>Vincolo</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="r in rules.rotation_rules" :key="r.food_group_or_item">
                                        <td>{{ r.food_group_or_item }}</td>
                                        <td>{{ r.min_per_week ?? '—' }}</td>
                                        <td>{{ r.max_per_week ?? '—' }}</td>
                                        <td>
                                            <span :class="r.is_hard_constraint ? 'badge-hard' : 'badge-soft'">
                                                {{ r.is_hard_constraint ? 'Rigido' : 'Soft' }}
                                            </span>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <p v-else-if="!rules.plan_rules" class="hint">Nessuna regola di rotazione definita nel piano.</p>

                        <!-- Grammature legacy (solo se plan_rules non disponibile) -->
                        <div v-if="!rules.plan_rules && rules.grammi_targets && Object.keys(rules.grammi_targets).length" class="rules-section">
                            <h4>Target nutrizionali</h4>
                            <div v-for="(targets, mealType) in rules.grammi_targets" :key="mealType" class="meal-targets">
                                <h5>{{ mealType === 'pranzo' ? 'Pranzo' : 'Cena' }}</h5>
                                <div v-for="(v, fg) in targets" :key="fg" class="target-row">
                                    <span class="target-fg">{{ fg }}</span>
                                    <span class="target-qty">{{ Math.round(v.qty) }} {{ v.unit }}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- MODALITÀ EDITING -->
                <div v-else class="rules-edit-form">
                    <div class="rules-section">
                        <h4>Grammi target</h4>
                        <table class="rules-table">
                            <thead>
                                <tr>
                                    <th>Pasto</th>
                                    <th>Carboidrati (g)</th>
                                    <th>Proteine (g)</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>Pranzo</td>
                                    <td><input v-model.number="editedRules.carb_target.pranzo" type="number" min="0" step="5" style="width:80px"></td>
                                    <td><input v-model.number="editedRules.protein_target.pranzo" type="number" min="0" step="5" style="width:80px"></td>
                                </tr>
                                <tr>
                                    <td>Cena</td>
                                    <td><input v-model.number="editedRules.carb_target.cena" type="number" min="0" step="5" style="width:80px"></td>
                                    <td><input v-model.number="editedRules.protein_target.cena" type="number" min="0" step="5" style="width:80px"></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="rules-section">
                        <h4>Frequenze settimanali</h4>
                        <table class="rules-table">
                            <thead>
                                <tr>
                                    <th>Categoria proteica</th>
                                    <th>Min / sett.</th>
                                    <th>Max / sett.</th>
                                    <th>Max rigido</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="(ft, cat) in editedRules.frequency_targets" :key="cat">
                                    <td><strong>{{ cat }}</strong></td>
                                    <td><input v-model.number="ft.min" type="number" min="0" max="14" style="width:60px"></td>
                                    <td><input v-model.number="ft.max" type="number" min="0" max="14" style="width:60px"></td>
                                    <td><input v-model.number="ft.hard_max" type="number" min="0" max="14" style="width:60px" placeholder="—"></td>
                                    <td><button @click="removeFreqCategory(cat)" class="btn-sm btn-danger">×</button></td>
                                </tr>
                                <tr>
                                    <td colspan="5">
                                        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
                                            <input v-model="newFreqCategory"
                                                   placeholder="Es. carne_bianca"
                                                   style="width:180px"
                                                   @keyup.enter="addFrequencyCategory">
                                            <button @click="addFrequencyCategory" class="btn-sm btn-primary">+ Aggiungi</button>
                                        </div>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div style="display:flex;gap:10px;margin-top:16px;">
                        <button @click="saveRules" class="btn-primary" :disabled="savingRules">
                            {{ savingRules ? 'Salvataggio...' : '💾 Salva' }}
                        </button>
                        <button @click="cancelEditRules" class="btn-secondary">Annulla</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            newProfileId: '',
            newProfileName: '',
            selectedProfile: null,
            rules: null,
            loadingRules: false,
            // Edit mode
            editingRules: false,
            savingRules: false,
            editedRules: {
                carb_target: { pranzo: 80, cena: 60 },
                protein_target: { pranzo: 150, cena: 120 },
                frequency_targets: {},
            },
            newFreqCategory: '',
        };
    },
    mounted() {
        this.fetchProfiles();
    },
    methods: {
        async fetchProfiles() {
            try {
                const resp = await fetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length && !this.selectedProfile) {
                    await this.selectProfile(this.profiles[0]);
                }
            } catch (e) {
                console.error('Error fetching profiles:', e);
            }
        },
        async createProfile() {
            try {
                const resp = await fetch('/profiles/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: this.newProfileId, name: this.newProfileName }),
                });
                if (!resp.ok) {
                    const err = await resp.json();
                    throw new Error(err.detail || 'Errore');
                }
                this.newProfileId = '';
                this.newProfileName = '';
                await this.fetchProfiles();
                this.toast.add('Profilo creato!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        async selectProfile(profile) {
            this.selectedProfile = profile;
            this.editingRules = false;
            this.rules = null;
            this.loadingRules = true;
            try {
                const resp = await fetch(`/planner/rules?profile_id_A=${profile.id}`);
                if (resp.ok) {
                    this.rules = await resp.json();
                }
            } catch (e) {
                console.error('Error fetching rules:', e);
            } finally {
                this.loadingRules = false;
            }
        },
        startEditRules() {
            const pr = this.rules?.plan_rules || {};
            this.editedRules = {
                carb_target: {
                    pranzo: pr.carb_target?.pranzo ?? 80,
                    cena: pr.carb_target?.cena ?? 60,
                },
                protein_target: {
                    pranzo: pr.protein_target?.pranzo ?? 150,
                    cena: pr.protein_target?.cena ?? 120,
                },
                frequency_targets: JSON.parse(JSON.stringify(pr.frequency_targets || {})),
            };
            this.newFreqCategory = '';
            this.editingRules = true;
        },
        cancelEditRules() {
            this.editingRules = false;
            this.newFreqCategory = '';
        },
        async saveRules() {
            this.savingRules = true;
            try {
                const resp = await fetch(`/planner/rules/${this.selectedProfile.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.editedRules),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.editingRules = false;
                // Ricarica le regole
                const rulesResp = await fetch(`/planner/rules?profile_id_A=${this.selectedProfile.id}`);
                if (rulesResp.ok) this.rules = await rulesResp.json();
                this.toast.add('Vincoli salvati!', 'success');
            } catch (e) {
                this.toast.add('Errore nel salvataggio: ' + e.message, 'error');
            } finally {
                this.savingRules = false;
            }
        },
        addFrequencyCategory() {
            const cat = this.newFreqCategory.trim();
            if (!cat) return;
            this.editedRules.frequency_targets = {
                ...this.editedRules.frequency_targets,
                [cat]: { min: 1, max: 3, hard_max: null },
            };
            this.newFreqCategory = '';
        },
        removeFreqCategory(cat) {
            const updated = { ...this.editedRules.frequency_targets };
            delete updated[cat];
            this.editedRules.frequency_targets = updated;
        },
    },
});

export default Profiles;
