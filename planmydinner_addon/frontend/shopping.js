import { defineComponent } from 'vue';

const ShoppingList = defineComponent({
    name: 'ShoppingList',
    inject: ['toast'],
    template: `
        <div class="shopping-view">
            <div class="shopping-header">
                <h2>Lista della Spesa</h2>
                <div class="date-picker-row">
                    <label>Dal</label>
                    <input type="date" v-model="startDate" @change="loadShoppingList" />
                    <span class="date-range-label">→ {{ endDateLabel }}</span>
                    <button @click="goToToday" class="btn-today">Oggi</button>
                </div>
            </div>

            <div v-if="loading" class="loading">Caricamento...</div>
            <div v-if="error" class="error-box">{{ error }}</div>

            <div v-if="!loading && !error && profiles.length < 2">
                <p>Crea almeno 2 profili per generare la lista della spesa.</p>
            </div>

            <div v-if="!loading && !error && profiles.length >= 2 && !shoppingData && localItems.length === 0">
                <p>Nessun piano per questo range. Vai in Settimana e genera prima il piano.</p>
                <button @click="showAddForm = true" class="btn-secondary" style="margin-top:8px">+ Aggiungi articolo manualmente</button>
            </div>

            <div v-if="shoppingData || localItems.length > 0">
                <!-- Azioni globali -->
                <div class="shopping-actions">
                    <a v-if="shoppingData" :href="csvUrl" download="lista_spesa.csv" class="btn-export">Esporta CSV</a>
                    <button @click="copyToClipboard" class="btn-copy">Copia negli appunti</button>
                    <label class="toggle-label">
                        <input type="checkbox" v-model="showPerProfile" /> Per persona
                    </label>
                    <button v-if="doneCount > 0" @click="clearDone" class="btn-secondary" style="font-size:13px">
                        Rimuovi {{ doneCount }} presi ✓
                    </button>
                    <button @click="showAddForm = !showAddForm" class="btn-secondary" style="font-size:13px">
                        {{ showAddForm ? '✕ Chiudi' : '+ Aggiungi' }}
                    </button>
                </div>

                <!-- Form aggiunta manuale -->
                <div v-if="showAddForm" class="add-item-form">
                    <input v-model="newItem.name" placeholder="Nome articolo" @keyup.enter="addItem" />
                    <input v-model.number="newItem.quantity" type="number" min="0" placeholder="Qtà" style="width:80px" @keyup.enter="addItem" />
                    <select v-model="newItem.unit" style="width:70px">
                        <option>g</option><option>kg</option><option>ml</option><option>l</option><option>pz</option>
                    </select>
                    <select v-model="newItem.category" style="width:130px">
                        <option value="">— categoria —</option>
                        <option v-for="cat in availableCategories" :key="cat" :value="cat">{{ cat }}</option>
                        <option value="altro">altro</option>
                    </select>
                    <button @click="addItem" class="btn-primary">Aggiungi</button>
                </div>

                <!-- Lista per categoria -->
                <div v-for="(items, category) in itemsByCategory" :key="category" class="category-section">
                    <h3 @click="toggleCategory(category)" class="category-header">
                        <span class="cat-icon">{{ categoryIcon(category) }}</span>
                        {{ category }}
                        <span class="cat-count">({{ items.filter(i => !i.done).length }}/{{ items.length }})</span>
                        <span class="collapse-arrow">{{ collapsedCategories[category] ? '▶' : '▼' }}</span>
                    </h3>
                    <ul v-if="!collapsedCategories[category]" class="item-list">
                        <li v-for="item in items" :key="item._id" class="shopping-item" :class="{ 'item-done': item.done }">
                            <!-- Checkbox preso -->
                            <input type="checkbox" :checked="item.done" @change="toggleDone(item)"
                                   class="item-check" :title="item.done ? 'Già in dispensa' : 'Segna come preso (va in dispensa)'" />
                            <!-- Nome (inline edit) -->
                            <span v-if="!item.editing" class="item-name" @dblclick="startEdit(item)">{{ item.name }}</span>
                            <input v-else class="item-name-input" v-model="item.name"
                                   @blur="item.editing = false" @keyup.enter="item.editing = false"
                                   @keyup.escape="item.editing = false" ref="editInput" />
                            <!-- Quantità (inline edit) -->
                            <span v-if="!item.editingQty" class="item-qty"
                                  @dblclick="item.editingQty = true">{{ formatQty(item) }}</span>
                            <span v-if="item.editingQty" class="item-qty-edit">
                                <input type="number" v-model.number="item.quantity" min="0" style="width:60px"
                                       @blur="item.editingQty = false" @keyup.enter="item.editingQty = false" />
                                <select v-model="item.unit" style="width:55px" @blur="item.editingQty = false">
                                    <option>g</option><option>kg</option><option>ml</option><option>l</option><option>pz</option>
                                </select>
                            </span>
                            <!-- Note per persona -->
                            <span v-if="showPerProfile && item.notes" class="item-profile-detail">{{ item.notes }}</span>
                            <!-- Tasto elimina -->
                            <button @click="removeItem(item)" class="btn-item-delete" title="Rimuovi">✕</button>
                        </li>
                    </ul>
                </div>

                <div v-if="totalVisible === 0 && localItems.length > 0" class="hint">
                    Tutti gli articoli sono stati presi! 🎉
                </div>
            </div>
        </div>
    `,
    data() {
        const now = new Date();
        const today = now.toISOString().slice(0, 10);
        const daysToMonday = now.getDay() === 0 ? 6 : now.getDay() - 1;
        const monday = new Date(now);
        monday.setDate(now.getDate() - daysToMonday);
        const mondayStr = monday.toISOString().slice(0, 10);
        return {
            profiles: [],
            shoppingData: null,
            localItems: [],          // lista editabile locale
            loading: false,
            error: null,
            collapsedCategories: {},
            showPerProfile: false,
            startDate: mondayStr,
            today,
            showAddForm: false,
            newItem: { name: '', quantity: '', unit: 'g', category: '' },
            _nextId: 1,
        };
    },
    computed: {
        profileA() { return this.profiles[0] || null; },
        profileB() { return this.profiles[1] || null; },
        endDateLabel() {
            if (!this.startDate) return '';
            const end = new Date(this.startDate + 'T12:00:00');
            end.setDate(end.getDate() + 6);
            return end.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
        },
        csvUrl() {
            if (!this.profileA || !this.profileB) return '#';
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB.id,
                start_date: this.startDate,
            });
            return '/shopping-list/export/csv?' + params;
        },
        itemsByCategory() {
            const grouped = {};
            for (const item of this.localItems) {
                const cat = item.category || 'altro';
                if (!grouped[cat]) grouped[cat] = [];
                grouped[cat].push(item);
            }
            return grouped;
        },
        availableCategories() {
            return [...new Set(this.localItems.map(i => i.category).filter(Boolean))];
        },
        doneCount() { return this.localItems.filter(i => i.done).length; },
        totalVisible() { return this.localItems.filter(i => !i.done).length; },
    },
    mounted() { this.loadData(); },
    methods: {
        // ── Caricamento ───────────────────────────────────────────────────
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const resp = await window.apiFetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) await this.loadShoppingList();
            } catch (e) {
                this.error = 'Errore nel caricamento: ' + e.message;
            } finally {
                this.loading = false;
            }
        },
        async loadShoppingList() {
            if (!this.profileA) return;
            this.shoppingData = null;
            this.localItems = [];
            this.error = null;
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB?.id || '',
                start_date: this.startDate,
            });
            try {
                const resp = await window.apiFetch('/shopping-list?' + params);
                if (!resp.ok) return;
                this.shoppingData = await resp.json();
                this.buildLocalItems();
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            }
        },
        buildLocalItems() {
            this.localItems = [];
            if (!this.shoppingData) return;
            for (const [category, items] of Object.entries(this.shoppingData.items_by_category)) {
                for (const item of items) {
                    this.localItems.push({
                        _id: this._nextId++,
                        name: item.name,
                        quantity: item.quantity,
                        unit: item.unit || 'g',
                        category,
                        notes: item.notes || '',
                        done: false,
                        editing: false,
                        editingQty: false,
                    });
                }
            }
        },

        // ── Interazioni ───────────────────────────────────────────────────
        async toggleDone(item) {
            if (item.done) {
                // de-seleziona senza toccare dispensa
                item.done = false;
                return;
            }
            // Segna come preso → manda in dispensa
            item.done = true;
            await this.addToPantry(item);
        },
        async addToPantry(item) {
            try {
                const body = [{
                    name: item.name,
                    quantity: item.quantity,
                    unit: item.unit,
                    category: item.category || null,
                }];
                const resp = await window.apiFetch('/pantry/items/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error(await resp.text());
                this.toast.add(`"${item.name}" aggiunto alla dispensa ✓`, 'success');
            } catch (e) {
                this.toast.add('Errore dispensa: ' + e.message, 'error');
                item.done = false;
            }
        },
        removeItem(item) {
            this.localItems = this.localItems.filter(i => i._id !== item._id);
        },
        clearDone() {
            this.localItems = this.localItems.filter(i => !i.done);
        },

        // ── Aggiunta manuale ──────────────────────────────────────────────
        addItem() {
            const name = (this.newItem.name || '').trim();
            if (!name) return;
            this.localItems.push({
                _id: this._nextId++,
                name,
                quantity: this.newItem.quantity || 0,
                unit: this.newItem.unit || 'g',
                category: this.newItem.category || 'altro',
                notes: '',
                done: false,
                editing: false,
                editingQty: false,
            });
            this.newItem = { name: '', quantity: '', unit: 'g', category: this.newItem.category };
        },

        // ── Edit inline ───────────────────────────────────────────────────
        startEdit(item) {
            item.editing = true;
        },

        // ── Utility ───────────────────────────────────────────────────────
        goToToday() {
            const now = new Date();
            const daysToMonday = now.getDay() === 0 ? 6 : now.getDay() - 1;
            const monday = new Date(now);
            monday.setDate(now.getDate() - daysToMonday);
            this.startDate = monday.toISOString().slice(0, 10);
            this.loadShoppingList();
        },
        toggleCategory(category) {
            this.collapsedCategories[category] = !this.collapsedCategories[category];
        },
        categoryIcon(cat) {
            const map = {
                carboidrati: '🌾', carboidrato: '🌾',
                proteina: '🥩', proteine: '🥩',
                verdure: '🥦', verdura: '🥦',
                frutta: '🍎', latticini: '🧀',
                grasso: '🫒', grassi: '🫒',
                altro: '📦',
            };
            return map[cat?.toLowerCase()] || '🛒';
        },
        formatQty(item) {
            const q = item.quantity;
            if (!q && q !== 0) return '—';
            return (Number.isInteger(q) ? q : Math.round(q)) + ' ' + (item.unit || 'g');
        },
        copyToClipboard() {
            const lines = [];
            for (const [category, items] of Object.entries(this.itemsByCategory)) {
                lines.push(`\n== ${category.toUpperCase()} ==`);
                for (const item of items) {
                    const done = item.done ? ' ✓' : '';
                    lines.push(`- ${item.name}: ${this.formatQty(item)}${item.notes ? ' (' + item.notes + ')' : ''}${done}`);
                }
            }
            navigator.clipboard.writeText(lines.join('\n'))
                .then(() => this.toast.add('Lista copiata negli appunti!', 'success'))
                .catch(() => this.toast.add('Errore nella copia.', 'error'));
        },
    },
});

export default ShoppingList;
