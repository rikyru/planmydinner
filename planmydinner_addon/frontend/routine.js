import { defineComponent } from 'vue';
import MensaModal from './mensa.js?v=5';

/**
 * Strip "Colazione & spuntini" (vista Oggi): pasti fissi con logica opt-out.
 * Gli slot definiti vengono assunti consumati ogni giorno; qui si gestiscono
 * solo le eccezioni (saltato / diverso / opt-in tipo gelato dopo cena) e la
 * definizione dei pasti tipo.
 */
const RoutineStrip = defineComponent({
    name: 'RoutineStrip',
    inject: ['toast'],
    components: { MensaModal },
    props: {
        profileId: { type: String, required: true },
        mealDate: { type: String, required: true },
    },
    emits: ['changed'],
    template: `
        <div class="card routine-strip">
            <div style="display:flex;align-items:center;gap:8px;">
                <strong style="font-size:14px;">☕ Colazione & spuntini</strong>
                <span v-if="definedSlots.length" class="hint">~{{ assumedKcal }} kcal oggi</span>
                <button @click="editorOpen = true" class="btn-sm btn-secondary" style="margin-left:auto;">⚙️</button>
            </div>

            <div v-if="loading" class="hint" style="margin-top:6px;">Caricamento…</div>

            <div v-else-if="!definedSlots.length" class="hint" style="margin-top:6px;">
                Definisci una volta la tua colazione e le merende tipo: verranno contate
                nei totali ogni giorno senza doverle registrare.
                <button @click="editorOpen = true" class="btn-sm btn-primary" style="margin-left:6px;">Definisci</button>
            </div>

            <div v-else style="display:flex;flex-direction:column;gap:6px;margin-top:8px;">
                <div v-for="s in definedSlots" :key="s.slot" class="routine-row">
                    <span style="font-size:15px;">{{ s.icon }}</span>
                    <span class="routine-row__name">
                        {{ s.name }}
                        <span v-if="s.nutrition" class="hint">~{{ Math.round(s.nutrition.kcal) }} kcal</span>
                    </span>
                    <!-- Stato / azioni del giorno -->
                    <template v-if="s.default_on">
                        <button v-if="s.today === 'assumed'" @click="toggleSkip(s)" class="chip chip--on" title="Tocca se oggi l'hai saltata">✓</button>
                        <button v-else-if="s.today === 'skipped'" @click="toggleSkip(s)" class="chip chip--off" title="Segnata come saltata — tocca per ripristinare">✗ saltata</button>
                        <span v-else class="chip chip--logged" title="Registrato un pasto diverso">✎ diversa</span>
                    </template>
                    <template v-else>
                        <button v-if="s.today === 'off'" @click="toggleLog(s)" class="chip chip--add" title="Segna per oggi">＋</button>
                        <button v-else-if="s.today === 'logged'" @click="toggleLog(s)" class="chip chip--on" title="Segnata — tocca per togliere">✓</button>
                        <button v-else-if="s.today === 'skipped'" @click="toggleSkip(s)" class="chip chip--off">✗</button>
                    </template>
                    <button @click="mensaSlot = s" class="btn-sm btn-secondary" title="Oggi qualcosa di diverso (foto/descrizione)">≠</button>
                </div>
            </div>

            <!-- Pasto diverso per uno slot -->
            <mensa-modal v-if="mensaSlot"
                         :profile-id="profileId"
                         :meal-type="mensaSlot.slot"
                         :meal-label="mensaSlot.label"
                         :meal-date="mealDate"
                         @close="mensaSlot = null"
                         @saved="onChanged" />

            <!-- Editor pasti fissi -->
            <div v-if="editorOpen" class="modal-overlay" @click.self="closeEditor">
                <div class="modal">
                    <h3>☕ Pasti fissi</h3>
                    <p class="hint" style="margin:0 0 10px;">
                        Vengono contati automaticamente nei totali di ogni giorno.
                        "Dopo cena" è l'eccezione: conta solo quando lo segni.
                    </p>

                    <div v-for="s in slots" :key="s.slot" style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:8px;">
                        <div style="display:flex;align-items:center;gap:8px;cursor:pointer;" @click="toggleEdit(s)">
                            <span>{{ s.icon }}</span>
                            <strong style="flex:1;font-size:13.5px;">{{ s.label }}</strong>
                            <span v-if="s.defined" class="hint">{{ s.name }} · ~{{ s.nutrition ? Math.round(s.nutrition.kcal) : '?' }} kcal</span>
                            <span v-else class="hint">non definito</span>
                            <span style="color:var(--text-3);">{{ editSlot === s.slot ? '▲' : '✏️' }}</span>
                        </div>

                        <div v-if="editSlot === s.slot" style="margin-top:10px;display:flex;flex-direction:column;gap:8px;">
                            <div style="display:flex;gap:8px;">
                                <input v-model="editForm.description"
                                       placeholder="es. caffè, 2 fette biscottate con marmellata, yogurt greco"
                                       :disabled="analyzing" @keyup.enter="analyzeDescription">
                                <button @click="analyzeDescription" class="btn-primary btn-sm"
                                        :disabled="analyzing || editForm.description.trim().length < 3" style="flex-shrink:0;">
                                    {{ analyzing ? '…' : '✨' }}
                                </button>
                            </div>
                            <input v-model="editForm.name" placeholder="Nome (es. Colazione tipo)">
                            <div v-for="(ing, idx) in editForm.ingredients" :key="idx"
                                 style="display:grid;grid-template-columns:1fr 80px auto;gap:8px;align-items:center;">
                                <input v-model="ing.name">
                                <input v-model.number="ing.grams" type="number" min="0" step="5">
                                <button @click="editForm.ingredients.splice(idx, 1)" class="btn-secondary btn-sm">✕</button>
                            </div>
                            <button @click="editForm.ingredients.push({name: '', food_group: 'altro', grams: 50})"
                                    class="btn-secondary btn-sm" style="align-self:flex-start;">+ ingrediente</button>
                            <label class="toggle-label">
                                <input type="checkbox" v-model="editForm.default_on" style="width:auto;">
                                Conta ogni giorno automaticamente
                            </label>
                            <div style="display:flex;gap:8px;">
                                <button @click="saveSlot(s)" class="btn-primary btn-sm"
                                        :disabled="saving || !editForm.name || !editForm.ingredients.length">
                                    {{ saving ? 'Salvataggio…' : '💾 Salva' }}
                                </button>
                                <button v-if="s.defined" @click="deleteSlot(s)" class="btn-danger btn-sm" style="margin-left:auto;">🗑️</button>
                            </div>
                            <div v-if="editError" class="error">{{ editError }}</div>
                        </div>
                    </div>

                    <button @click="closeEditor" class="btn-secondary" style="margin-top:8px;">Chiudi</button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            slots: [],
            loading: false,
            editorOpen: false,
            editSlot: null,
            editForm: { description: '', name: '', ingredients: [], default_on: true },
            analyzing: false,
            saving: false,
            editError: null,
            mensaSlot: null,
        };
    },
    computed: {
        definedSlots() { return this.slots.filter(s => s.defined); },
        assumedKcal() {
            return Math.round(this.definedSlots.reduce((sum, s) => {
                if (!s.nutrition) return sum;
                const counts = (s.default_on && s.today !== 'skipped' && s.today !== 'logged')
                    || (!s.default_on && s.today === 'logged');
                return counts ? sum + s.nutrition.kcal : sum;
            }, 0));
        },
    },
    mounted() { this.load(); },
    methods: {
        async load() {
            this.loading = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId, target_date: this.mealDate });
                const resp = await window.apiFetch('/routine/?' + params);
                this.slots = resp.ok ? (await resp.json()).slots : [];
            } catch (_) {
                this.slots = [];
            } finally {
                this.loading = false;
            }
        },
        async onChanged() {
            this.mensaSlot = null;
            await this.load();
            this.$emit('changed');
        },
        async toggleSkip(s) {
            try {
                const params = new URLSearchParams({ profile_id: this.profileId, meal_date: this.mealDate });
                const resp = await window.apiFetch(`/routine/${s.slot}/skip?` + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const r = await resp.json();
                this.toast.add(r.state === 'skipped' ? `${s.label} saltata oggi` : `${s.label} ripristinata`, 'info');
                await this.onChanged();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        async toggleLog(s) {
            try {
                const params = new URLSearchParams({ profile_id: this.profileId, meal_date: this.mealDate });
                const resp = await window.apiFetch(`/routine/${s.slot}/log?` + params, { method: 'POST' });
                if (!resp.ok) throw new Error(await resp.text());
                const r = await resp.json();
                this.toast.add(r.state === 'logged' ? `${s.icon} ${s.name} segnato!` : `${s.label} tolta`, 'success');
                await this.onChanged();
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        toggleEdit(s) {
            if (this.editSlot === s.slot) { this.editSlot = null; return; }
            this.editSlot = s.slot;
            this.editError = null;
            this.editForm = {
                description: '',
                name: s.name || '',
                ingredients: (s.ingredients || []).map(i => ({ ...i })),
                default_on: s.default_on,
            };
        },
        async analyzeDescription() {
            const description = this.editForm.description.trim();
            if (description.length < 3) return;
            this.analyzing = true;
            this.editError = null;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/consumed-entries/text/analyze?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ description }),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || 'Analisi fallita.');
                }
                const proposal = await resp.json();
                this.editForm.name = this.editForm.name || proposal.name;
                this.editForm.ingredients = proposal.ingredients;
            } catch (e) {
                this.editError = e.message;
            } finally {
                this.analyzing = false;
            }
        },
        async saveSlot(s) {
            this.saving = true;
            this.editError = null;
            try {
                const body = {
                    profile_id: this.profileId,
                    name: this.editForm.name,
                    ingredients: this.editForm.ingredients.filter(i => i.name && i.grams > 0),
                    default_on: this.editForm.default_on,
                };
                const resp = await window.apiFetch(`/routine/${s.slot}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add(`${s.label} salvata!`, 'success');
                this.editSlot = null;
                await this.load();
                this.$emit('changed');
            } catch (e) {
                this.editError = 'Errore: ' + e.message;
            } finally {
                this.saving = false;
            }
        },
        async deleteSlot(s) {
            if (!confirm(`Rimuovere "${s.name}" da ${s.label}?`)) return;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch(`/routine/${s.slot}?` + params, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                this.editSlot = null;
                await this.load();
                this.$emit('changed');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        closeEditor() {
            this.editorOpen = false;
            this.editSlot = null;
        },
    },
});

export default RoutineStrip;
