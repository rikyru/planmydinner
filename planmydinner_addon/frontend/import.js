import { defineComponent } from 'vue';

const ImportWizard = defineComponent({
    name: 'ImportWizard',
    inject: ['toast'],
    template: `
        <div class="import-view">
            <h2>Importa Piano Alimentare</h2>

            <!-- ── Step 1: Upload ──────────────────────────────────── -->
            <div v-if="!parsedData">
                <div class="tab-bar">
                    <button @click="activeTab = 'pdf'" :class="{active: activeTab === 'pdf'}">PDF</button>
                    <button @click="activeTab = 'text'" :class="{active: activeTab === 'text'}">Testo</button>
                </div>

                <div class="import-form">
                    <label>Profilo</label>
                    <select v-model="selectedProfile">
                        <option :value="null" disabled>Seleziona un profilo...</option>
                        <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name }}</option>
                    </select>

                    <div v-if="activeTab === 'pdf'" class="tab-panel">
                        <p class="hint">Carica il PDF del tuo nutrizionista. Il testo verrà estratto e analizzato dall'IA.</p>
                        <input type="file" @change="onFileChange" accept=".pdf">
                        <button class="btn-primary" @click="uploadPdf" :disabled="!file || !selectedProfile || uploading">
                            {{ uploading ? 'Analisi in corso...' : 'Carica e analizza PDF' }}
                        </button>
                    </div>

                    <div v-if="activeTab === 'text'" class="tab-panel">
                        <p class="hint">Incolla il testo del piano alimentare.</p>
                        <textarea v-model="textContent" rows="12" placeholder="Lunedì&#10;Pranzo: pasta al pomodoro 80g..."></textarea>
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

            <!-- ── Step 2: Preview ─────────────────────────────────── -->
            <div v-if="parsedData">
                <div class="preview-header">
                    <h3>Rivedi prima di salvare</h3>
                    <p style="color:#868e96; font-size:13px;">Profilo: <strong>{{ parsedData.profile_id }}</strong></p>
                </div>

                <!-- Sezione: Criteri capiti -->
                <div class="preview-section">
                    <div class="preview-section__title" @click="showCriteri = !showCriteri">
                        <span>📋 Criteri capiti dall'IA</span>
                        <span class="collapse-arrow">{{ showCriteri ? '▼' : '▶' }}</span>
                    </div>
                    <div v-if="showCriteri" class="preview-section__body">
                        <p style="font-size:12px; color:#868e96; margin:0 0 10px">Puoi modificare i valori prima di salvare.</p>
                        <div class="criteri-grid">
                            <!-- Grammi target carbo -->
                            <div class="criteri-box">
                                <h5>Carboidrati target (g)</h5>
                                <table class="criteri-table">
                                    <tr v-for="mt in ['pranzo','cena']" :key="mt">
                                        <td>{{ mt }}</td>
                                        <td>
                                            <input type="number" v-model.number="editableTargets.carb[mt]"
                                                   class="criteri-input-sm" min="0" max="500" placeholder="—"> g
                                        </td>
                                    </tr>
                                </table>
                            </div>
                            <!-- Grammi target proteine -->
                            <div class="criteri-box">
                                <h5>Proteine target (g)</h5>
                                <table class="criteri-table">
                                    <tr v-for="mt in ['pranzo','cena']" :key="mt">
                                        <td>{{ mt }}</td>
                                        <td>
                                            <input type="number" v-model.number="editableTargets.protein[mt]"
                                                   class="criteri-input-sm" min="0" max="500" placeholder="—"> g
                                        </td>
                                    </tr>
                                </table>
                            </div>
                            <!-- Opzioni carboidrati -->
                            <div class="criteri-box">
                                <h5>Opzioni carboidrati</h5>
                                <p style="font-size:11px;color:#868e96;margin:0 0 6px">Separati da virgola</p>
                                <table class="criteri-table">
                                    <tr v-for="mt in ['pranzo','cena']" :key="mt">
                                        <td style="white-space:nowrap">{{ mt }}</td>
                                        <td>
                                            <input type="text" v-model="editableOptions.carb[mt]"
                                                   class="criteri-input" placeholder="pasta, riso, farro...">
                                        </td>
                                    </tr>
                                </table>
                            </div>
                            <!-- Opzioni proteine -->
                            <div class="criteri-box">
                                <h5>Opzioni proteine</h5>
                                <p style="font-size:11px;color:#868e96;margin:0 0 6px">Separati da virgola</p>
                                <table class="criteri-table">
                                    <tr v-for="mt in ['pranzo','cena']" :key="mt">
                                        <td style="white-space:nowrap">{{ mt }}</td>
                                        <td>
                                            <input type="text" v-model="editableOptions.protein[mt]"
                                                   class="criteri-input" placeholder="pollo, salmone, uova...">
                                        </td>
                                    </tr>
                                </table>
                            </div>
                            <!-- Frequenze + pasti liberi -->
                            <div class="criteri-box" style="grid-column: 1 / -1">
                                <h5>Frequenze settimanali</h5>
                                <table class="criteri-table">
                                    <thead>
                                        <tr>
                                            <th>Alimento</th><th>Min/sett</th><th>Max/sett</th><th>Hard</th><th></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="(r, i) in (parsedData.rotation_rules || [])" :key="i">
                                            <td>
                                                <input v-model="r.food_group_or_item" class="criteri-input"
                                                       placeholder="es. carne_rossa">
                                            </td>
                                            <td>
                                                <input type="number" v-model.number="r.min_per_week"
                                                       class="criteri-input-sm" min="0" placeholder="—">
                                            </td>
                                            <td>
                                                <input type="number" v-model.number="r.max_per_week"
                                                       class="criteri-input-sm" min="0" placeholder="—">
                                            </td>
                                            <td style="text-align:center">
                                                <input type="checkbox" v-model="r.is_hard_constraint">
                                            </td>
                                            <td>
                                                <button @click="parsedData.rotation_rules.splice(i,1)"
                                                        class="btn-danger" style="padding:2px 7px; font-size:11px">✕</button>
                                            </td>
                                        </tr>
                                        <tr v-if="!(parsedData.rotation_rules || []).length">
                                            <td colspan="5" style="color:#adb5bd">Nessuna regola estratta</td>
                                        </tr>
                                    </tbody>
                                </table>
                                <button @click="addFrequencyRule()" class="btn-secondary"
                                        style="margin-top:8px; font-size:12px; padding:4px 10px">+ Aggiungi regola</button>
                                <div style="margin-top:12px; display:flex; align-items:center; gap:10px">
                                    <label style="font-size:13px; font-weight:500">Pasti liberi/settimana:</label>
                                    <input type="number" v-model.number="editableFreeMealQuota"
                                           class="criteri-input-sm" min="0" max="14" placeholder="Nessun limite"
                                           style="width:80px">
                                    <span style="font-size:12px; color:#868e96">(lascia vuoto = nessun limite)</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sezione: Ricette trovate -->
                <div class="preview-section">
                    <div class="preview-section__title" @click="showRicette = !showRicette">
                        <span>🍽️ Ricette trovate ({{ uniqueRecipes.filter(r => r.include).length }}/{{ uniqueRecipes.length }} selezionate)</span>
                        <span class="collapse-arrow">{{ showRicette ? '▼' : '▶' }}</span>
                    </div>
                    <div v-if="showRicette" class="preview-section__body">
                        <p style="font-size:13px; color:#868e96; margin:0 0 10px">
                            Deseleziona le ricette che non vuoi salvare nel tuo ricettario.
                        </p>
                        <div v-if="uniqueRecipes.length === 0" class="hint">Nessuna ricetta estratta.</div>
                        <div v-for="r in uniqueRecipes" :key="r.fp" class="recipe-import-row"
                             :class="{ 'recipe-import-row--off': !r.include }">
                            <input type="checkbox" v-model="r.include" class="item-check" />
                            <div class="recipe-import-info">
                                <input v-model="r.name" class="recipe-import-name"
                                       :disabled="!r.include" placeholder="Nome ricetta" />
                                <div class="recipe-import-items">
                                    <span v-for="(item, i) in r.items" :key="i" class="recipe-import-item">
                                        {{ item.item_name }}
                                        <span v-if="item.quantity" style="color:#adb5bd">{{ item.quantity }}{{ item.unit }}</span>
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sezione: Piano giornaliero -->
                <div class="preview-section">
                    <div class="preview-section__title" @click="showPiano = !showPiano">
                        <span>📅 Piano giornaliero ({{ parsedData.daily_plans.length }} giorni)</span>
                        <span class="collapse-arrow">{{ showPiano ? '▼' : '▶' }}</span>
                    </div>
                    <div v-if="showPiano" class="preview-section__body">
                        <p style="font-size:12px; color:#868e96; margin:0 0 12px">
                            Deseleziona i pasti che vuoi lasciare vuoti nel piano importato.
                        </p>
                        <div v-for="day in parsedData.daily_plans" :key="day.date" class="day-preview">
                            <h4 class="day-preview-title">{{ formatDate(day.date) }}</h4>
                            <div v-for="meal in day.meals" :key="meal.meal_type" class="meal-preview">
                                <div class="meal-preview__header">
                                    <h5>{{ meal.meal_type === 'pranzo' ? '☀️ Pranzo' : '🌙 Cena' }}</h5>
                                    <label class="meal-include-label">
                                        <input type="checkbox" v-model="meal._include">
                                        <span>{{ meal._include ? 'Incluso' : 'Escludi (lascia vuoto)' }}</span>
                                    </label>
                                </div>
                                <template v-if="meal._include">
                                    <div v-if="!meal.items || meal.items.length === 0"
                                         style="color:#adb5bd; font-size:13px; padding:4px 0">Nessun alimento</div>
                                    <table v-else class="items-table">
                                        <thead><tr><th>Alimento</th><th>Qtà</th><th>Unità</th><th>Gruppo</th></tr></thead>
                                        <tbody>
                                            <tr v-for="(item, idx) in meal.items" :key="idx">
                                                <td><input v-model="item.item_name" class="item-input"></td>
                                                <td><input v-model.number="item.quantity" type="number" class="qty-input"></td>
                                                <td><input v-model="item.unit" class="unit-input"></td>
                                                <td><input v-model="item.food_group" class="group-input"></td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </template>
                                <div v-else class="meal-skip-notice">Questo pasto verrà lasciato vuoto nel piano.</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Azioni finali -->
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
            parsedPlanRules: null,
            uniqueRecipes: [],   // [{fp, name, items, include}]
            editableTargets: { carb: {}, protein: {} },
            editableOptions: { carb: { pranzo: '', cena: '' }, protein: { pranzo: '', cena: '' } },
            editableFreeMealQuota: null,
            profiles: [],
            selectedProfile: null,
            uploading: false,
            saving: false,
            uploadError: null,
            // collapse state
            showCriteri: true,
            showRicette: true,
            showPiano: false,
        };
    },
    mounted() { this.fetchProfiles(); },
    methods: {
        async fetchProfiles() {
            try {
                const resp = await fetch('/profiles/');
                if (resp.ok) this.profiles = await resp.json();
            } catch (e) { /* silenzioso */ }
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
                const result = await resp.json();
                this.parsedData = result.plan;
                this.parsedPlanRules = result.plan_rules || null;
                this._buildUniqueRecipes();
                this._initEditableState();
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
                const result = await resp.json();
                this.parsedData = result.plan;
                this.parsedPlanRules = result.plan_rules || null;
                this._buildUniqueRecipes();
                this._initEditableState();
            } catch (e) {
                this.uploadError = e.message;
            } finally {
                this.uploading = false;
            }
        },
        async save() {
            this.saving = true;
            try {
                // Deep copy to avoid mutating reactive state
                const plan = JSON.parse(JSON.stringify(this.parsedData));
                // Apply include/skip flags
                for (const day of plan.daily_plans || []) {
                    for (const meal of day.meals || []) {
                        if (!meal._include) meal.items = [];
                        delete meal._include;
                    }
                }
                const skipNames = this.uniqueRecipes
                    .filter(r => !r.include)
                    .map(r => r.name);

                // Build plan_rules_override from editable fields.
                // If original plan_rules had rich objects {name,quantity,...}, rebuild them;
                // otherwise fall back to simple name strings.
                const pr = this.parsedPlanRules || {};
                const buildOptions = (editedStr, originalOpts) => {
                    const names = (editedStr || '').split(',').map(s => s.trim()).filter(Boolean);
                    if (!names.length) return null;
                    const origMap = {};
                    for (const o of (originalOpts || [])) {
                        const n = (typeof o === 'object' && o !== null) ? o.name : o;
                        origMap[n] = o;
                    }
                    return names.map(n => origMap[n] || n);
                };
                const carbOptions = {};
                const proteinOptions = {};
                for (const mt of ['pranzo', 'cena']) {
                    const c = buildOptions(this.editableOptions.carb[mt], (pr.carb_options || {})[mt]);
                    if (c) carbOptions[mt] = c;
                    const p = buildOptions(this.editableOptions.protein[mt], (pr.protein_options || {})[mt]);
                    if (p) proteinOptions[mt] = p;
                }
                const plan_rules_override = {
                    carb_target: this.editableTargets.carb,
                    protein_target: this.editableTargets.protein,
                    carb_options: Object.keys(carbOptions).length ? carbOptions : null,
                    protein_options: Object.keys(proteinOptions).length ? proteinOptions : null,
                    meal_slots: pr.meal_slots || null,
                    free_meal_quota: this.editableFreeMealQuota ?? null,
                };

                const resp = await fetch('/import/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        plan,
                        skip_recipe_names: skipNames,
                        plan_rules_override,
                    }),
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
            this.parsedPlanRules = null;
            this.uniqueRecipes = [];
            this.editableTargets = { carb: {}, protein: {} };
            this.editableOptions = { carb: { pranzo: '', cena: '' }, protein: { pranzo: '', cena: '' } };
            this.editableFreeMealQuota = null;
            this.file = null;
            this.textContent = '';
            this.selectedProfile = null;
            this.uploadError = null;
        },
        formatDate(dateString) {
            const d = new Date(dateString + 'T12:00:00');
            return d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
        },
        _initEditableState() {
            // Add _include flag to each meal
            for (const day of this.parsedData.daily_plans || []) {
                for (const meal of day.meals || []) {
                    meal._include = true;
                }
            }
            if (this.parsedPlanRules) {
                const pr = this.parsedPlanRules;
                // Gram targets
                this.editableTargets = {
                    carb: { ...(pr.carb_target || {}) },
                    protein: { ...(pr.protein_target || {}) },
                };
                // Options: convert arrays to comma-separated strings (handles both str and {name,...} formats)
                const optName = o => (typeof o === 'object' && o !== null) ? o.name : o;
                const toStr = (opts, mt) => ((opts || {})[mt] || []).map(optName).join(', ');
                this.editableOptions = {
                    carb: {
                        pranzo: toStr(pr.carb_options, 'pranzo'),
                        cena: toStr(pr.carb_options, 'cena'),
                    },
                    protein: {
                        pranzo: toStr(pr.protein_options, 'pranzo'),
                        cena: toStr(pr.protein_options, 'cena'),
                    },
                };
                this.editableFreeMealQuota = pr.free_meal_quota ?? null;
            } else {
                // Fallback: derive from daily_plans by averaging
                const carbSums = {}, proteinSums = {};
                const carbFGs = ['carboidrati', 'carboidrato'];
                const proteinFGs = ['proteina', 'proteine', 'pollo', 'pesce', 'carne_rossa', 'legumi', 'uova'];
                for (const day of this.parsedData.daily_plans || []) {
                    for (const meal of day.meals || []) {
                        const mt = meal.meal_type;
                        for (const item of meal.items || []) {
                            const fg = (item.food_group || '').toLowerCase();
                            const qty = item.quantity || 0;
                            if (carbFGs.includes(fg) && qty > 0) (carbSums[mt] = carbSums[mt] || []).push(qty);
                            if (proteinFGs.includes(fg) && qty > 0) (proteinSums[mt] = proteinSums[mt] || []).push(qty);
                        }
                    }
                }
                const avg = obj => Object.fromEntries(
                    Object.entries(obj).map(([k, v]) => [k, Math.round(v.reduce((a, b) => a + b, 0) / v.length)])
                );
                this.editableTargets = {
                    carb: avg(carbSums),
                    protein: avg(proteinSums),
                };
                this.editableOptions = { carb: { pranzo: '', cena: '' }, protein: { pranzo: '', cena: '' } };
                this.editableFreeMealQuota = null;
            }
        },
        _buildUniqueRecipes() {
            const seen = new Set();
            const recipes = [];
            for (const day of this.parsedData?.daily_plans || []) {
                for (const meal of day.meals || []) {
                    if (!meal.items || meal.items.length === 0) continue;
                    const fp = meal.items.map(i => (i.item_name || '').toLowerCase().trim()).sort().join('|');
                    if (seen.has(fp)) continue;
                    seen.add(fp);
                    recipes.push({
                        fp,
                        name: this._buildName(meal.items),
                        items: meal.items.map(i => ({ ...i })),
                        include: true,
                    });
                }
            }
            this.uniqueRecipes = recipes;
        },
        _buildName(items) {
            const order = ['proteina', 'pollo', 'carne_rossa', 'pesce', 'legumi', 'uova', 'carboidrati', 'verdure'];
            const sorted = [...items].sort((a, b) => {
                const ia = order.indexOf(a.food_group); const ib = order.indexOf(b.food_group);
                return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
            });
            const names = sorted.slice(0, 3).map(i => i.item_name);
            if (names.length === 1) return names[0];
            if (names.length === 2) return `${names[0]} con ${names[1]}`;
            return `${names[0]} con ${names[1]} e ${names[2]}`;
        },
        addFrequencyRule() {
            if (!this.parsedData.rotation_rules) this.parsedData.rotation_rules = [];
            this.parsedData.rotation_rules.push({
                food_group_or_item: '',
                min_per_week: null,
                max_per_week: null,
                is_hard_constraint: false,
            });
        },
    },
});

export default ImportWizard;
