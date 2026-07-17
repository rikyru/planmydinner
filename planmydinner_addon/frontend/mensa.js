import { defineComponent } from 'vue';

/**
 * Ridimensiona a max 1600px e ricodifica in JPEG: upload leggero anche con
 * foto da 12MP (evita il limite 10MB) e normalizza i formati (HEIC).
 */
export async function prepareImage(file) {
    try {
        const bmp = await createImageBitmap(file);
        const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
        if (scale === 1 && file.type === 'image/jpeg' && file.size < 2 * 1024 * 1024) return file;
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(bmp.width * scale);
        canvas.height = Math.round(bmp.height * scale);
        canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.85));
        return blob ? new File([blob], 'pasto.jpg', { type: 'image/jpeg' }) : file;
    } catch (_) {
        return file;   // formato non decodificabile lato client: prova comunque
    }
}

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
                <h3>📷 Pasto da foto — {{ mealType === 'pranzo' ? 'Pranzo' : 'Cena' }} {{ dateLabel }}</h3>

                <!-- Fase 1: catalogo + scatto/caricamento foto -->
                <div v-if="!proposal">
                    <div v-if="loading" class="loading">Caricamento catalogo...</div>
                    <template v-else>
                        <div v-if="meals.length" style="margin-bottom:10px;">
                            <div style="font-size:13px;font-weight:600;margin-bottom:6px;">Salvati — tap per registrare:</div>
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
                        <div v-else style="font-size:13px;color:var(--text-3);margin-bottom:10px;">
                            Nessun pasto salvato: fotografa il piatto (mensa, ristorante, casa...) per iniziare il catalogo.
                        </div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            <label class="btn-consumed" style="display:inline-block;cursor:pointer;">
                                {{ analyzing ? '🔎 Analisi in corso...' : '📷 Scatta foto' }}
                                <input type="file" accept="image/*" capture="environment" style="display:none"
                                       :disabled="analyzing" @change="analyzePhoto">
                            </label>
                            <label class="btn-secondary" style="display:inline-block;cursor:pointer;">
                                🖼️ Dalla galleria
                                <input type="file" accept="image/*" style="display:none"
                                       :disabled="analyzing" @change="analyzePhoto">
                            </label>
                        </div>
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
                const prepared = await prepareImage(file);
                const form = new FormData();
                form.append('file', prepared, prepared.name || 'pasto.jpg');
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
