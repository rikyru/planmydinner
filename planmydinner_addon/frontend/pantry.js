import { defineComponent } from 'vue';

const Pantry = defineComponent({
    inject: ['toast'],
    template: `
        <div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <h2 style="margin:0">Dispensa</h2>
                <button class="btn-primary" @click="startScan">📷 Scansiona barcode</button>
                <button class="btn-secondary" @click="addItem">+ Aggiungi a mano</button>
            </div>

            <!-- In scadenza → ricette che li consumano -->
            <div v-if="expiringInfo.expiring.length" class="card" style="margin-top:12px;border:1px solid #d6282855;">
                <strong>⏰ In scadenza</strong>
                <span class="hint"> — {{ expiringInfo.expiring.map(e => e.name + (e.days < 0 ? ' (scaduto)' : ' (' + e.days + 'g)')).join(', ') }}</span>
                <div v-if="expiringInfo.recipes.length" style="margin-top:8px;">
                    <div class="hint" style="margin-bottom:4px;">Ricette che li usano:</div>
                    <div v-for="r in expiringInfo.recipes" :key="r.id" style="margin-bottom:3px;">
                        🍽 <strong>{{ r.name }}</strong> <span class="hint">— usa {{ r.uses.join(', ') }}</span>
                    </div>
                </div>
                <div v-else class="hint" style="margin-top:6px;">Nessuna ricetta in catalogo usa questi prodotti.</div>
            </div>

            <!-- Scanner fotocamera -->
            <div v-if="scanning" class="modal-overlay" @click.self="stopScan">
                <div class="modal" style="max-width:420px;">
                    <h3>Inquadra il codice a barre</h3>
                    <video ref="video" autoplay playsinline muted
                           style="width:100%;border-radius:8px;background:#000;max-height:50vh;"></video>
                    <label style="display:flex;align-items:center;gap:6px;margin:8px 0;font-size:13px;">
                        <input type="checkbox" v-model="continuous"> Scansione continua (aggiungi al volo, poi metti le scadenze)
                    </label>
                    <div v-if="continuous && addedCount" class="hint" style="color:#2a9d8f;">✓ aggiunti: {{ addedCount }}</div>
                    <p class="hint">Oppure inserisci il codice a mano:</p>
                    <div style="display:flex;gap:6px;">
                        <input v-model="manualCode" placeholder="Es. 8001120..." style="flex:1;" @keyup.enter="lookup(manualCode)">
                        <button class="btn-sm btn-primary" @click="lookup(manualCode)">Cerca</button>
                    </div>
                    <div style="margin-top:10px;"><button class="btn-secondary" @click="stopScan">Chiudi</button></div>
                </div>
            </div>

            <table class="recipe-table" style="margin-top:12px;">
                <thead>
                    <tr><th>Prodotto</th><th>Quantità</th><th>Scadenza</th><th>Macro /100g</th><th>Azioni</th></tr>
                </thead>
                <tbody>
                    <tr v-for="item in sortedItems" :key="item.id" :class="{'row-to-fix': isExpiring(item)}">
                        <td>
                            {{ item.name }}
                            <span v-if="item.barcode" class="hint" style="font-size:11px;">· {{ item.barcode }}</span>
                        </td>
                        <td>{{ item.quantity }} {{ item.unit }}</td>
                        <td>
                            <span v-if="item.expiration_date" :style="isExpiring(item) ? 'color:#d62828;font-weight:600' : ''">
                                {{ item.expiration_date }}{{ daysLabel(item) }}
                            </span>
                            <span v-else class="hint">—</span>
                        </td>
                        <td class="hint" style="font-size:11px;">
                            <span v-if="item.nutrition">{{ Math.round(item.nutrition.kcal||0) }} kcal · P {{ item.nutrition.protein_g }} · C {{ item.nutrition.carbs_g }} · G {{ item.nutrition.fat_g }}</span>
                            <span v-else>—</span>
                        </td>
                        <td>
                            <button class="btn-sm" @click="editItem(item)">Modifica</button>
                            <button class="btn-sm btn-danger" @click="deleteItem(item.id)">Elimina</button>
                        </td>
                    </tr>
                </tbody>
            </table>

            <div class="modal-overlay" v-if="showModal" @click.self="closeModal">
                <div class="modal">
                    <h3>{{ editedItem.id ? 'Modifica prodotto' : 'Aggiungi prodotto' }}</h3>
                    <div v-if="editedItem.nutrition" class="hint" style="margin-bottom:8px;">
                        🧾 {{ Math.round(editedItem.nutrition.kcal||0) }} kcal · P {{ editedItem.nutrition.protein_g }} · C {{ editedItem.nutrition.carbs_g }} · G {{ editedItem.nutrition.fat_g }} <span>(per 100 g)</span>
                    </div>
                    <label>Nome</label>
                    <input v-model="editedItem.name" placeholder="Es. Fagioli cannellini">
                    <div style="display:flex;gap:8px;">
                        <label style="flex:1;">Quantità<input v-model.number="editedItem.quantity" type="number" min="0" step="10"></label>
                        <label style="width:90px;">Unità<input v-model="editedItem.unit" placeholder="g"></label>
                    </div>
                    <label>Scadenza</label>
                    <input v-model="editedItem.expiration_date" type="date">
                    <div style="display:flex;gap:10px;margin-top:14px;">
                        <button class="btn-primary" @click="saveItem" :disabled="!editedItem.name">Salva</button>
                        <button class="btn-secondary" @click="closeModal">Annulla</button>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            items: [],
            expiringInfo: { expiring: [], recipes: [] },
            showModal: false,
            editedItem: {},
            scanning: false,
            continuous: false,
            addedCount: 0,
            manualCode: '',
            _stream: null,
            _detectTimer: null,
            _lastCode: null,
            _lastAt: 0,
        };
    },
    computed: {
        sortedItems() {
            // in scadenza prima
            return [...this.items].sort((a, b) =>
                (a.expiration_date || '9999').localeCompare(b.expiration_date || '9999'));
        },
    },
    methods: {
        fetchItems() {
            window.apiFetch('/pantry/items').then(r => r.json()).then(d => { this.items = d; });
            this.fetchExpiring();
        },
        fetchExpiring() {
            window.apiFetch('/pantry/expiring-recipes')
                .then(r => r.json()).then(d => { this.expiringInfo = d; })
                .catch(() => {});
        },
        _daysTo(item) {
            if (!item.expiration_date) return null;
            const d = new Date(item.expiration_date + 'T12:00:00');
            return Math.round((d - new Date()) / 86400000);
        },
        isExpiring(item) {
            const n = this._daysTo(item);
            return n !== null && n <= 3;
        },
        daysLabel(item) {
            const n = this._daysTo(item);
            if (n === null) return '';
            if (n < 0) return ' (scaduto)';
            if (n === 0) return ' (oggi)';
            if (n <= 3) return ` (${n}g)`;
            return '';
        },
        addItem() {
            this.editedItem = { unit: 'g' };
            this.showModal = true;
        },
        editItem(item) {
            this.editedItem = { ...item };
            this.showModal = true;
        },
        closeModal() { this.showModal = false; },
        saveItem() {
            const method = this.editedItem.id ? 'PUT' : 'POST';
            const url = this.editedItem.id ? `/pantry/items/${this.editedItem.id}` : '/pantry/items';
            const body = {
                name: this.editedItem.name,
                quantity: Number(this.editedItem.quantity) || 0,
                unit: this.editedItem.unit || 'g',
                category: this.editedItem.category || null,
                expiration_date: this.editedItem.expiration_date || null,
                synonyms: this.editedItem.synonyms || [],
                barcode: this.editedItem.barcode || null,
                nutrition: this.editedItem.nutrition || null,
            };
            window.apiFetch(url, {
                method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            }).then(r => {
                if (!r.ok) throw new Error('salvataggio fallito');
                this.fetchItems(); this.closeModal();
            }).catch(e => this.toast && this.toast.add('Errore: ' + e.message, 'error'));
        },
        deleteItem(itemId) {
            window.apiFetch(`/pantry/items/${itemId}`, { method: 'DELETE' }).then(() => this.fetchItems());
        },
        // --- Barcode ---
        async startScan() {
            this.manualCode = '';
            this.addedCount = 0;
            this._lastCode = null;
            this.scanning = true;
            if (!('BarcodeDetector' in window)) {
                this.toast && this.toast.add('Scanner non supportato dal browser: inserisci il codice a mano.', 'info');
                return;
            }
            try {
                this._stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'environment' } });
                await this.$nextTick();
                const video = this.$refs.video;
                video.srcObject = this._stream;
                const detector = new window.BarcodeDetector({
                    formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128'] });
                const tick = async () => {
                    if (!this.scanning) return;
                    try {
                        const codes = await detector.detect(video);
                        if (codes && codes.length) {
                            if (this.continuous) {
                                await this.quickAdd(codes[0].rawValue);   // aggiunge e continua
                            } else {
                                this.lookup(codes[0].rawValue); return;   // prefill + stop
                            }
                        }
                    } catch (_) { /* frame non pronto */ }
                    this._detectTimer = setTimeout(tick, this.continuous ? 900 : 400);
                };
                this._detectTimer = setTimeout(tick, 600);
            } catch (e) {
                this.toast && this.toast.add('Fotocamera non disponibile: inserisci il codice a mano.', 'info');
            }
        },
        stopScan() {
            this.scanning = false;
            clearTimeout(this._detectTimer);
            if (this._stream) { this._stream.getTracks().forEach(t => t.stop()); this._stream = null; }
        },
        _parsePack(text) {
            const m = (text || '').match(/(\d+[.,]?\d*)\s*(kg|g|l|ml|cl)/i);
            if (!m) return { quantity: 1, unit: 'pz' };
            let q = parseFloat(m[1].replace(',', '.'));
            const u = m[2].toLowerCase();
            if (u === 'kg') return { quantity: q * 1000, unit: 'g' };
            if (u === 'l') return { quantity: q * 1000, unit: 'ml' };
            if (u === 'cl') return { quantity: q * 10, unit: 'ml' };
            return { quantity: q, unit: u };
        },
        async quickAdd(code) {
            const now = Date.now();
            if (code === this._lastCode && now - this._lastAt < 4000) return;  // dedupe stesso prodotto
            this._lastCode = code; this._lastAt = now;
            try {
                const p = await (await window.apiFetch('/pantry/barcode/' + encodeURIComponent(code))).json();
                if (!p.found) { this.toast && this.toast.add('Non trovato: ' + code, 'info'); return; }
                const pack = this._parsePack(p.quantity_text);
                await window.apiFetch('/pantry/items', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: [p.name, p.brands].filter(Boolean).join(' · ') || ('Prodotto ' + code),
                        quantity: pack.quantity, unit: pack.unit, barcode: code,
                        nutrition: p.nutrition || null, synonyms: [] }),
                });
                this.addedCount++;
                this.toast && this.toast.add('+ ' + (p.name || code), 'success');
                this.fetchItems();
            } catch (e) { this.toast && this.toast.add('Errore: ' + e.message, 'error'); }
        },
        async lookup(code) {
            code = (code || '').trim();
            if (!code) return;
            try {
                const r = await window.apiFetch('/pantry/barcode/' + encodeURIComponent(code));
                const p = await r.json();
                if (!p.found) {
                    this.toast && this.toast.add('Prodotto non trovato per ' + code + ': aggiungilo a mano.', 'info');
                    this.editedItem = { unit: 'g', barcode: code };
                } else {
                    const pack = this._parsePack(p.quantity_text);
                    this.editedItem = {
                        name: [p.name, p.brands].filter(Boolean).join(' · ') || ('Prodotto ' + code),
                        quantity: pack.quantity, unit: pack.unit,
                        barcode: code, nutrition: p.nutrition || null,
                    };
                    this.toast && this.toast.add('Trovato: ' + (p.name || code), 'success');
                }
                this.stopScan();
                this.showModal = true;
            } catch (e) {
                this.toast && this.toast.add('Errore ricerca barcode: ' + e.message, 'error');
            }
        },
    },
    beforeUnmount() { this.stopScan(); },
    mounted() { this.fetchItems(); },
});

export default Pantry;
