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
                <h3>Regole del Piano — {{ selectedProfile.name }}</h3>

                <div v-if="loadingRules" class="loading">Caricamento regole...</div>
                <div v-else-if="!rules">
                    <p class="hint">Nessun piano attivo trovato per questo profilo.<br>
                    Importa un piano nella sezione <em>Importa</em> per vedere le regole.</p>
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

                    <!-- PlanRules: frequenze settimanali (se disponibili, sostituisce rotation_rules) -->
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
                    <!-- Fallback: rotation_rules legacy (se plan_rules non disponibile) -->
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
                    <p v-else-if="!rules.plan_rules" class="hint">Nessun target grammi trovato nel piano.</p>
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
                // Auto-select first profile
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
    },
});

export default Profiles;
