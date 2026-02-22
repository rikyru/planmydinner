const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerShoppingListCard extends LitElement {
    static get properties() {
        return {
            hass: {},
            config: {},
            checked_items: { state: true },
        };
    }

    constructor() {
        super();
        this.checked_items = [];
    }

    setConfig(config) {
        if (!config.entity) {
            throw new Error("You need to define an entity");
        }
        this.config = config;
    }

    getCardSize() {
        return 5;
    }

    render() {
        if (!this.hass || !this.config) {
            return html``;
        }

        const entityId = this.config.entity;
        if (!entityId) {
            return html`
                <ha-card>
                    <div class="card-content">Error: You must define an entity in the card configuration.</div>
                </ha-card>
            `;
        }
        const state = this.hass.states[entityId];

        if (!state) {
            return html`
                <ha-card header="Lista della Spesa">
                    <div class="card-content">
                        Entity <strong>${entityId}</strong> not found. Please check your configuration.
                    </div>
                </ha-card>
            `;
        }
        
        const itemsByCategory = state.attributes.items_by_category || {};

        return html`
            <ha-card header="Lista della Spesa">
                <div class="card-content">
                    ${Object.keys(itemsByCategory).map(category => this._renderCategory(category, itemsByCategory[category]))}
                </div>
                <div class="card-actions">
                    <mwc-button @click=${this._clearList}>PULISCI LISTA</mwc-button>
                    <mwc-button raised @click=${this._exportToList}>ESPORTA A HA SHOPPING LIST</mwc-button>
                </div>
            </ha-card>
        `;
    }

    _renderCategory(category, items) {
        return html`
            <h3>${category}</h3>
            ${items.map(item => this._renderItem(item))}
        `;
    }

    _renderItem(item) {
        const itemId = `${item.name}-${item.unit}`;
        return html`
            <div class="item">
                <ha-checkbox
                    .checked=${this.checked_items.includes(itemId)}
                    @change=${e => this._itemChecked(e.target.checked, itemId)}
                ></ha-checkbox>
                <span>${item.name} - ${item.quantity} ${item.unit}</span>
            </div>
        `;
    }

    _itemChecked(isChecked, itemId) {
        if (isChecked) {
            this.checked_items = [...this.checked_items, itemId];
        } else {
            this.checked_items = this.checked_items.filter(id => id !== itemId);
        }
    }
    
    _clearList() {
        this.checked_items = [];
    }

    _exportToList() {
        const itemsByCategory = this.hass.states[this.config.entity].attributes.items_by_category || {};
        const allItems = Object.values(itemsByCategory).flat();

        allItems.forEach(item => {
            this.hass.callService("shopping_list", "add_item", {
                name: `${item.name} ${item.quantity} ${item.unit}`
            });
        });
    }

    static get styles() {
        return css`
            h3 {
                margin-top: 1em;
                margin-bottom: 0.5em;
            }
            .item {
                display: flex;
                align-items: center;
                padding: 4px 0;
            }
            .card-actions {
                display: flex;
                justify-content: flex-end;
                padding: 8px;
            }
        `;
    }
}

customElements.define("planmydinner-shopping-list-card", PlanMyDinnerShoppingListCard);
