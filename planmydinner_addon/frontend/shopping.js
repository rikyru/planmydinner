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
            <div v-if="error" class="error">{{ error }}</div>

            <div v-if="!loading && !error && profiles.length < 2">
                <p>Crea almeno 2 profili per generare la lista della spesa.</p>
            </div>

            <div v-if="!loading && !error && profiles.length >= 2 && !shoppingData">
                <p>Nessun piano per questo range. Vai in Settimana e genera prima il piano.</p>
            </div>

            <div v-if="shoppingData">
                <div class="shopping-actions">
                    <a :href="csvUrl" download="lista_spesa.csv" class="btn-export">Esporta CSV</a>
                    <button @click="copyToClipboard" class="btn-copy">Copia negli appunti</button>
                    <label class="toggle-label">
                        <input type="checkbox" v-model="showPerProfile" /> Mostra dettaglio per persona
                    </label>
                </div>

                <div v-if="totalItems === 0" class="hint">
                    La lista è vuota. Assicurati che i pasti abbiano un recipe_id (usa "Cambia" per assegnare ricette).
                </div>

                <div v-for="(items, category) in shoppingData.items_by_category" :key="category" class="category-section">
                    <h3 @click="toggleCategory(category)" class="category-header">
                        <span class="cat-icon">{{ categoryIcon(category) }}</span>
                        {{ category }}
                        <span class="cat-count">({{ items.length }})</span>
                        <span class="collapse-arrow">{{ collapsedCategories[category] ? '▶' : '▼' }}</span>
                    </h3>
                    <ul v-if="!collapsedCategories[category]" class="item-list">
                        <li v-for="item in items" :key="item.name" class="shopping-item">
                            <span class="item-name">{{ item.name }}</span>
                            <span class="item-qty">{{ Math.round(item.quantity) }}g</span>
                            <span v-if="showPerProfile && item.notes" class="item-profile-detail">{{ item.notes }}</span>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    `,
    data() {
        const today = new Date().toISOString().slice(0, 10);
        return {
            profiles: [],
            shoppingData: null,
            loading: false,
            error: null,
            collapsedCategories: {},
            showPerProfile: false,
            startDate: today,
            today,
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
        totalItems() {
            if (!this.shoppingData) return 0;
            return Object.values(this.shoppingData.items_by_category).reduce((s, arr) => s + arr.length, 0);
        },
    },
    mounted() {
        this.loadData();
    },
    methods: {
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                const resp = await fetch('/profiles/');
                this.profiles = await resp.json();
                if (this.profiles.length >= 2) {
                    await this.loadShoppingList();
                }
            } catch (e) {
                this.error = 'Errore nel caricamento: ' + e.message;
            } finally {
                this.loading = false;
            }
        },
        async loadShoppingList() {
            if (!this.profileA) return;
            this.shoppingData = null;
            this.error = null;
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB?.id || '',
                start_date: this.startDate,
            });
            try {
                const resp = await fetch('/shopping-list?' + params);
                if (!resp.ok) { this.shoppingData = null; return; }
                this.shoppingData = await resp.json();
            } catch (e) {
                this.error = 'Errore: ' + e.message;
            }
        },
        goToToday() {
            this.startDate = this.today;
            this.loadShoppingList();
        },
        toggleCategory(category) {
            this.collapsedCategories[category] = !this.collapsedCategories[category];
        },
        categoryIcon(cat) {
            const map = { carboidrati: '🌾', carboidrato: '🌾', proteina: '🥩', proteine: '🥩', verdure: '🥦', verdura: '🥦', frutta: '🍎', latticini: '🧀', grasso: '🫒', altro: '📦' };
            return map[cat] || '🛒';
        },
        copyToClipboard() {
            if (!this.shoppingData) return;
            const lines = [];
            for (const [category, items] of Object.entries(this.shoppingData.items_by_category)) {
                lines.push(`\n== ${category.toUpperCase()} ==`);
                for (const item of items) {
                    lines.push(`- ${item.name}: ${Math.round(item.quantity)}g${item.notes ? ' (' + item.notes + ')' : ''}`);
                }
            }
            navigator.clipboard.writeText(lines.join('\n')).then(() => {
                this.toast.add('Lista copiata negli appunti!', 'success');
            }).catch(() => {
                this.toast.add('Errore nella copia.', 'error');
            });
        },
    },
});

export default ShoppingList;
