import { defineComponent } from 'vue';

const Pantry = defineComponent({
    template: `
        <div>
            <h2>Pantry</h2>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Quantity</th>
                        <th>Unit</th>
                        <th>Expiration Date</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="item in items" :key="item.id">
                        <td>{{ item.name }}</td>
                        <td>{{ item.quantity }}</td>
                        <td>{{ item.unit }}</td>
                        <td>{{ item.expiration_date }}</td>
                        <td>
                            <button @click="editItem(item)">Edit</button>
                            <button @click="deleteItem(item.id)">Delete</button>
                        </td>
                    </tr>
                </tbody>
            </table>
            <button @click="addItem">Add Item</button>
            
            <div class="modal" v-if="showModal">
                <div class="modal-content">
                    <h3>{{ editedItem.id ? 'Edit Item' : 'Add Item' }}</h3>
                    <input v-model="editedItem.name" placeholder="Name">
                    <input v-model="editedItem.quantity" placeholder="Quantity" type="number">
                    <input v-model="editedItem.unit" placeholder="Unit">
                    <input v-model="editedItem.expiration_date" placeholder="Expiration Date" type="date">
                    <button @click="saveItem">Save</button>
                    <button @click="closeModal">Cancel</button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            items: [],
            showModal: false,
            editedItem: {},
        }
    },
    methods: {
        fetchItems() {
            window.apiFetch('/pantry/items')
                .then(response => response.json())
                .then(data => {
                    this.items = data;
                });
        },
        addItem() {
            this.editedItem = {};
            this.showModal = true;
        },
        editItem(item) {
            this.editedItem = { ...item };
            this.showModal = true;
        },
        closeModal() {
            this.showModal = false;
        },
        saveItem() {
            const method = this.editedItem.id ? 'PUT' : 'POST';
            const url = this.editedItem.id ? `/pantry/items/${this.editedItem.id}` : '/pantry/items';

            window.apiFetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.editedItem),
            })
            .then(() => {
                this.fetchItems();
                this.closeModal();
            });
        },
        deleteItem(itemId) {
            window.apiFetch(`/pantry/items/${itemId}`, { method: 'DELETE' })
                .then(() => {
                    this.fetchItems();
                });
        }
    },
    mounted() {
        this.fetchItems();
    }
});

export default Pantry;

