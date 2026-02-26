import { defineComponent } from 'vue';

const ShoppingList = defineComponent({
    name: 'ShoppingList',
    inject: ['toast'],
    template: `
        <div class="shopping-view">
            <h2>Lista della Spesa</h2>

            <div v-if="loading" class="loading">Caricamento...</div>
            <div v-if="error" class="error">{{ error }}</div>

            <div v-if="!loading && !error && profiles.length < 2">
                <p>Crea almeno 2 profili per generare la lista della spesa.</p>
            </div>

            <div v-if="!loading && !error && profiles.length >= 2 && !shoppingData">
                <p>Nessun piano disponibile per questa settimana.</p>
            </div>

            <div v-if="shoppingData">
                <div class="shopping-actions">
                    <a :href="csvUrl" download="lista_spesa.csv" class="btn-export">Esporta CSV</a>
                    <button @click="copyToClipboard" class="btn-copy">Copia negli appunti</button>
                </div>

                <div v-for="(items, category) in shoppingData.items_by_category" :key="category" class="category-section">
                    <h3 @click="toggleCategory(category)" class="category-header">
                        {{ category }} ({{ items.length }})
                        <span>{{ collapsedCategories[category] ? '▶' : '▼' }}</span>
                    </h3>
                    <ul v-if="!collapsedCategories[category]" class="item-list">
                        <li v-for="item in items" :key="item.name" class="shopping-item">
                            <span class="item-name">{{ item.name }}</span>
                            <span class="item-qty">{{ Math.round(item.quantity) }} {{ item.unit }}</span>
                            <span v-if="item.notes" class="item-notes">{{ item.notes }}</span>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            shoppingData: null,
            loading: false,
            error: null,
            collapsedCategories: {},
            today: new Date().toISOString().slice(0, 10),
        };
    },
    computed: {
        profileA() { return this.profiles[0] || null; },
        profileB() { return this.profiles[1] || null; },
        csvUrl() {
            if (!this.profileA || !this.profileB) return '#';
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB.id,
                start_date: this.today,
            });
            return '/shopping-list/export/csv?' + params;
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
            const params = new URLSearchParams({
                profile_id_A: this.profileA.id,
                profile_id_B: this.profileB.id,
                start_date: this.today,
            });
            const resp = await fetch('/shopping-list?' + params);
            if (!resp.ok) {
                this.shoppingData = null;
                return;
            }
            this.shoppingData = await resp.json();
        },
        toggleCategory(category) {
            this.collapsedCategories[category] = !this.collapsedCategories[category];
        },
        copyToClipboard() {
            if (!this.shoppingData) return;
            const lines = [];
            for (const [category, items] of Object.entries(this.shoppingData.items_by_category)) {
                lines.push(`\n== ${category.toUpperCase()} ==`);
                for (const item of items) {
                    lines.push(`- ${item.name}: ${Math.round(item.quantity)} ${item.unit}`);
                }
            }
            navigator.clipboard.writeText(lines.join('\n')).then(() => {
                this.toast.add('Lista copiata negli appunti!', 'success');
            }).catch(() => {
                this.toast.add('Errore nella copia negli appunti.', 'error');
            });
        },
    },
});

export default ShoppingList;
