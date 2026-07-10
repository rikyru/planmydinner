import { defineComponent } from 'vue';

/**
 * Modal "pasto da foto / catalogo mensa", condiviso fra la vista Oggi e la
 * vista Settimana. Registra il consumo per (profileId, mealDate, mealType).
 * Eventi: 'saved' dopo una registrazione riuscita, 'close' per chiudere.
 */
const MensaModal = defineComponent({
    name: 'MensaModal',
    inject: ['toast'],
    props: {
        profileId: { type: String, required: true },
        mealType: { type: String, required: true },
        mealDate: { type: String, required: true },
    },
    emits: ['close', 'saved'],
    template: `
        <div class="modal-overlay" @click.self="$emit('close')">
            <div class="modal">
                <h3>📷 Pasto mensa — {{ mealType === 'pranzo' ? 'Pranzo' : 'Cena' }} {{ dateLabel }}</h3>

                <!-- Fase 1: catalogo + scatto foto -->
                <div v-if="!proposal">
                    <div v-if="loading" class="loading">Caricamento catalogo...</div>
                    <template v-else>
                        <div v-if="meals.length" style="margin-bottom:10px;">
                            <div style="font-size:13px;font-weight:600;margin-bottom:6px;">Già mappati — tap per registrare:</div>
                            <div v-for="m in meals" :key="m.id" class="recipe-option" @click="consume(m)">
                                <strong>{{ m.name }}</strong>
                                <span v-if="m.nutrition">
                                    ~{{ Math.round(m.nutrition.kcal) }} kcal ·
                                    P {{ Math.round(m.nutrition.protein_g) }}g ·
                                    C {{ Math.round(m.nutrition.carbs_g) }}g ·
                                    G {{ Math.round(m.nutrition.fat_g) }}g
                                </span>
                                <span>{{ m.ingredients.map(i => i.name).join(', ') }}</span>
                            </div>
                        </div>
                        <div v-else style="font-size:13px;color:#6c757d;margin-bottom:10px;">
                            Nessun pasto mensa mappato: fotografa il vassoio per iniziare il catalogo.
                        </div>
                        <label class="btn-consumed" style="display:inline-block;cursor:pointer;">
                            {{ analyzing ? '🔎 Analisi foto in corso...' : '📷 Scatta / carica foto' }}
                            <input type="file" accept="image/*" capture="environment" style="display:none"
                                   :disabled="analyzing" @change="analyzePhoto">
                        </label>
                    </template>
                    <div v-if="error" class="error">{{ error }}</div>
                </div>

                <!-- Fase 2: conferma/correzione proposta -->
                <div v-else>
                    <div class="custom-form">
                        <label>Nome del pasto</label>
                        <input v-model="proposal.name">
                        <label>Ingredienti stimati (correggi se serve)</label>
                        <div v-for="(ing, idx) in proposal.ingredients" :key="idx" class="custom-row">
                            <input v-model="ing.name" style="flex:2">
                            <input v-model.number="ing.grams" type="number" min="0" step="10" style="width:80px">
                            <button @click="proposal.ingredients.splice(idx, 1)" class="btn-secondary">✕</button>
                        </div>
                        <div v-if="proposal.nutrition" style="font-size:13px;margin-top:8px;">
                            Stima: <strong>~{{ Math.round(proposal.nutrition.kcal) }} kcal</strong>
                            · P {{ Math.round(proposal.nutrition.protein_g) }}g
                            · C {{ Math.round(proposal.nutrition.carbs_g) }}g
                            · G {{ Math.round(proposal.nutrition.fat_g) }}g
                        </div>
                    </div>
                    <div style="display:flex;gap:10px;margin-top:14px;">
                        <button @click="save" class="btn-consumed"
                                :disabled="!proposal.name || !proposal.ingredients.length || saving">
                            {{ saving ? 'Salvataggio...' : '✓ Salva e registra' }}
                        </button>
                        <button @click="proposal = null" class="btn-secondary">↩ Indietro</button>
                    </div>
                    <div v-if="error" class="error">{{ error }}</div>
                </div>

                <button @click="$emit('close')" class="btn-secondary" style="margin-top:12px;">Chiudi</button>
            </div>
        </div>
    `,
    data() {
        return {
            meals: [],
            loading: false,
            error: null,
            analyzing: false,
            proposal: null,
            saving: false,
        };
    },
    computed: {
        dateLabel() {
            const todayIso = new Date().toISOString().slice(0, 10);
            if (this.mealDate === todayIso) return '';
            const d = new Date(this.mealDate + 'T12:00:00');
            return '— ' + d.toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
        },
    },
    mounted() {
        this.loadCatalog();
    },
    methods: {
        async loadCatalog() {
            this.loading = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/consumed-entries/mensa?' + params);
                this.meals = resp.ok ? await resp.json() : [];
            } catch (_) {
                this.meals = [];
            } finally {
                this.loading = false;
            }
        },
        async analyzePhoto(ev) {
            const file = ev.target.files?.[0];
            if (!file) return;
            this.analyzing = true;
            this.error = null;
            try {
                const form = new FormData();
                form.append('file', file);
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/consumed-entries/photo/analyze?' + params, {
                    method: 'POST',
                    body: form,   // niente Content-Type: lo imposta il browser (multipart)
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Analisi fallita.');
                }
                this.proposal = await resp.json();
            } catch (e) {
                this.error = e.message;
            } finally {
                this.analyzing = false;
                ev.target.value = '';   // permette di ricaricare lo stesso file
            }
        },
        async save() {
            if (!this.proposal?.name) return;
            this.saving = true;
            this.error = null;
            try {
                const body = {
                    profile_id: this.profileId,
                    date: this.mealDate,
                    meal_type: this.mealType,
                    name: this.proposal.name,
                    ingredients: this.proposal.ingredients.filter(i => i.name && i.grams > 0),
                };
                const resp = await window.apiFetch('/consumed-entries/mensa', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add(`"${body.name}" salvato e registrato!`, 'success');
                this.$emit('saved');
                this.$emit('close');
            } catch (e) {
                this.error = 'Errore nel salvataggio: ' + e.message;
            } finally {
                this.saving = false;
            }
        },
        async consume(meal) {
            try {
                const params = new URLSearchParams({
                    profile_id: this.profileId,
                    meal_date: this.mealDate,
                    meal_type: this.mealType,
                });
                const resp = await window.apiFetch(`/consumed-entries/mensa/${meal.id}/consume?` + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add(`"${meal.name}" registrato!`, 'success');
                this.$emit('saved');
                this.$emit('close');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
    },
});

export default MensaModal;
