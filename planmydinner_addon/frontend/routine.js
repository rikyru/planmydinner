import { defineComponent } from 'vue';
import MensaModal from './mensa.js?v=6';
import RoutineEditor from './routine-editor.js?v=1';
import { macroLine } from './meal-nutrition.js?v=4';

/**
 * Strip "Colazione & spuntini" (vista Oggi): pasti fissi con logica opt-out.
 * Gli slot definiti vengono assunti consumati ogni giorno; qui si gestiscono
 * solo le eccezioni (saltato / diverso / opt-in tipo gelato dopo cena) e la
 * definizione dei pasti tipo.
 */
const RoutineStrip = defineComponent({
    name: 'RoutineStrip',
    inject: ['toast'],
    components: { MensaModal, RoutineEditor },
    props: {
        profileId: { type: String, required: true },
        mealDate: { type: String, required: true },
    },
    emits: ['changed'],
    template: `
        <div class="card routine-strip">
            <div style="display:flex;align-items:center;gap:8px;">
                <strong style="font-size:14px;">☕ Colazione & spuntini</strong>
                <span v-if="shownSlots.length" class="hint">~{{ assumedKcal }} kcal oggi</span>
                <button @click="editorOpen = true" class="btn-sm btn-secondary" style="margin-left:auto;">⚙️</button>
            </div>

            <div v-if="loading" class="hint" style="margin-top:6px;">Caricamento…</div>

            <div v-else-if="!shownSlots.length" class="hint" style="margin-top:6px;">
                Definisci una volta la tua colazione e le merende tipo: verranno contate
                nei totali ogni giorno senza doverle registrare.
                <button @click="editorOpen = true" class="btn-sm btn-primary" style="margin-left:6px;">Definisci</button>
            </div>

            <div v-else style="display:flex;flex-direction:column;gap:6px;margin-top:8px;">
                <div v-for="s in shownSlots" :key="s.slot" class="routine-row">
                    <span style="font-size:15px;">{{ s.icon }}</span>
                    <span class="routine-row__name">
                        <span :style="s.today === 'skipped' ? 'text-decoration:line-through;opacity:.6' : ''">
                            {{ s.today_name ? '✎ ' + s.today_name : (s.name || s.label) }}
                        </span>
                        <span v-if="s.today_nutrition" class="routine-row__macros">{{ macroLine(s.today_nutrition) }}</span>
                        <span v-else-if="s.nutrition" class="routine-row__macros" style="opacity:.55">~{{ Math.round(s.nutrition.kcal) }} kcal se lo segni</span>
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

            <!-- Merende extra: spuntini liberi fuori dai 4 slot fissi -->
            <div v-if="!loading" style="margin-top:10px;border-top:1px dashed var(--border);padding-top:8px;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <strong style="font-size:13px;">🍫 Extra di oggi</strong>
                    <span v-if="extrasKcal" class="hint">+{{ extrasKcal }} kcal</span>
                    <button @click="showExtraForm = !showExtraForm" class="btn-sm btn-secondary" style="margin-left:auto;">+ Aggiungi</button>
                </div>
                <div v-for="x in extras" :key="x.id" class="routine-row" style="margin-top:6px;">
                    <span>🍪</span>
                    <span class="routine-row__name" :title="x.description || ''">{{ x.name }}<span v-if="x.nutrition" class="routine-row__macros">{{ macroLine(x.nutrition) }}</span></span>
                    <button @click="deleteExtra(x.id)" class="btn-sm btn-danger" title="Rimuovi">×</button>
                </div>
                <div v-if="showExtraForm" style="margin-top:8px;border:1px solid var(--border);border-radius:8px;padding:8px;">
                    <textarea v-model="extraForm.description" rows="2" style="width:100%;margin-bottom:4px;"
                              placeholder="Descrivi a parole (es. aperitivo: birra media, pane e salumi)"></textarea>
                    <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
                        <button @click="estimateExtra" class="btn-sm btn-primary"
                                :disabled="extraEstimating || (extraForm.description || '').trim().length < 3">
                            {{ extraEstimating ? 'Stimo…' : '✨ Stima con AI' }}</button>
                        <span v-if="extraEstimate" class="hint">≈ {{ macroLine(extraEstimate) }} · controlla i grammi qui sotto</span>
                        <span v-else class="hint">oppure inserisci gli ingredienti a mano</span>
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
                        <select v-model="pantryPick" @change="addFromPantry" style="flex:1;" @focus="loadPantry">
                            <option value="">📦 Aggiungi dalla dispensa…</option>
                            <option v-for="p in pantryChoices" :key="p.id" :value="p.id">
                                {{ pantryLabel(p) }}</option>
                        </select>
                    </div>
                    <input v-model="extraForm.name" placeholder="Nome (es. Barretta, Frutta, Aperitivo)" style="width:100%;margin-bottom:6px;">
                    <div v-for="(ing, idx) in extraForm.ingredients" :key="idx" style="display:flex;gap:6px;margin-bottom:4px;">
                        <input v-model="ing.name" placeholder="Ingrediente (es. mela)" style="flex:1;" :readonly="!!ing.pantry_id"
                               :title="ing.pantry_id ? 'dalla dispensa: valori da etichetta' : ''">
                        <span v-if="ing.per100" class="hint" style="align-self:center;white-space:nowrap;">📦 {{ Math.round(ing.per100.kcal * (ing.grams || 0) / 100) }} kcal</span>
                        <input v-model.number="ing.grams" type="number" min="0" step="10" placeholder="g" style="width:70px;">
                        <button @click="extraForm.ingredients.splice(idx, 1)" class="btn-sm btn-danger">×</button>
                    </div>
                    <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;">
                        <button @click="extraForm.ingredients.push({ name: '', food_group: 'altro', grams: 50 })" class="btn-sm">+ riga</button>
                        <button @click="submitExtra" class="btn-sm btn-primary" :disabled="!extraCanSave">Salva merenda</button>
                        <button @click="showExtraForm = false" class="btn-sm btn-secondary">Annulla</button>
                    </div>
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
                        Li trovi anche in Impostazioni.
                    </p>

                    <routine-editor :profile-id="profileId" @changed="onEditorChanged" />

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
            mensaSlot: null,
            extras: [],
            showExtraForm: false,
            extraForm: { name: '', description: '', ingredients: [{ name: '', food_group: 'altro', grams: 50 }] },
            extraEstimating: false,
            extraEstimate: null,
            pantryItems: null,
            pantryPick: '',
        };
    },
    computed: {
        definedSlots() { return this.slots.filter(s => s.defined); },
        // anche gli slot senza pasto fisso, se oggi c'è qualcosa registrato (es. merenda da foto)
        shownSlots() { return this.slots.filter(s => s.defined || s.today === 'logged'); },
        extrasKcal() {
            return Math.round(this.extras.reduce((s, x) => s + (x.nutrition ? x.nutrition.kcal : 0), 0));
        },
        pantryChoices() {
            // un prodotto scansionato più volte è più righe in dispensa: una sola voce
            // per nome; prima quelli con i valori dell'etichetta, poi gli altri
            const seen = new Set();
            return (this.pantryItems || []).filter(p => {
                const k = (p.name || '').trim().toLowerCase();
                return !seen.has(k) && seen.add(k);
            }).sort((a, b) =>
                (b.nutrition?.kcal != null) - (a.nutrition?.kcal != null) || a.name.localeCompare(b.name));
        },
        extraCanSave() {
            return this.extraForm.ingredients.some(i => (i.name || '').trim() && i.grams > 0);
        },
        assumedKcal() {
            // quello che conta davvero oggi (pasto fisso o diverso registrato)
            return Math.round(this.slots.reduce((sum, s) => sum + (s.today_nutrition ? s.today_nutrition.kcal : 0), 0));
        },
    },
    mounted() { this.load(); this.fetchExtras(); },
    watch: {
        mealDate() { this.load(); this.fetchExtras(); },
    },
    methods: {
        macroLine,
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
        async fetchExtras() {
            try {
                const params = new URLSearchParams({ profile_id: this.profileId, meal_date: this.mealDate });
                const resp = await window.apiFetch('/routine/extras?' + params);
                this.extras = resp.ok ? (await resp.json()).extras : [];
            } catch (_) {
                this.extras = [];
            }
        },
        async submitExtra() {
            const ingredients = this.extraForm.ingredients
                .filter(i => (i.name || '').trim() && i.grams > 0)
                .map(i => ({ name: i.name.trim(), food_group: i.food_group || 'altro', grams: i.grams,
                             pantry_id: i.pantry_id || null }));
            if (!ingredients.length) return;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId, meal_date: this.mealDate });
                const resp = await window.apiFetch('/routine/extra?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: this.extraForm.name || 'Merenda extra', ingredients,
                                           description: this.extraForm.description || '' }),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.showExtraForm = false;
                this.extraForm = { name: '', description: '', ingredients: [{ name: '', food_group: 'altro', grams: 50 }] };
                this.extraEstimate = null;
                await this.fetchExtras();
                this.$emit('changed');
                this.toast.add('Merenda extra aggiunta!', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            }
        },
        pantryLabel(p) {
            const k = p.nutrition && p.nutrition.kcal != null ? Math.round(p.nutrition.kcal) : null;
            return p.name + (k != null ? ' · ' + k + ' kcal/100g' : ' · (senza valori)');
        },
        async loadPantry() {
            if (this.pantryItems) return;
            try {
                const resp = await window.apiFetch('/pantry/items?limit=500');
                this.pantryItems = resp.ok ? await resp.json() : [];
            } catch (_) {
                this.pantryItems = [];
            }
        },
        // prodotto della dispensa -> riga ingrediente (100 g da correggere); il server
        // userà i valori per 100 g dell'etichetta
        addFromPantry() {
            const p = (this.pantryItems || []).find(x => x.id === this.pantryPick);
            this.pantryPick = '';
            if (!p) return;
            const rows = this.extraForm.ingredients.filter(i => (i.name || '').trim());
            const per100 = p.nutrition && p.nutrition.kcal != null ? p.nutrition : null;
            rows.push({ name: p.name, food_group: 'altro', grams: 100,
                        pantry_id: per100 ? p.id : null, per100 });
            this.extraForm.ingredients = rows;
            if (!this.extraForm.name) this.extraForm.name = p.name;
        },
        // descrizione libera -> ingredienti con grammi stimati (stessa analisi del
        // "pasto diverso"); l'utente li corregge prima di salvare
        async estimateExtra() {
            this.extraEstimating = true;
            try {
                const params = new URLSearchParams({ profile_id: this.profileId });
                const resp = await window.apiFetch('/consumed-entries/text/analyze?' + params, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ description: this.extraForm.description }),
                });
                if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
                const r = await resp.json();
                this.extraForm.name = this.extraForm.name || r.name;
                this.extraForm.ingredients = r.ingredients.map(i => ({
                    name: i.name, food_group: i.food_group || 'altro', grams: Math.round(i.grams) }));
                this.extraEstimate = r.nutrition;
            } catch (e) {
                this.toast.add('Stima non riuscita: ' + e.message, 'error');
            } finally {
                this.extraEstimating = false;
            }
        },
        async deleteExtra(id) {
            try {
                const resp = await window.apiFetch(`/routine/extra/${id}`, { method: 'DELETE' });
                if (!resp.ok) throw new Error(await resp.text());
                await this.fetchExtras();
                this.$emit('changed');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
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
        async onEditorChanged() {
            await this.load();
            this.$emit('changed');
        },
        closeEditor() {
            this.editorOpen = false;
        },
    },
});

export default RoutineStrip;
