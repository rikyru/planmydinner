const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerPantryItemCard extends LitElement {
    static get properties() {
        return {
            hass: {},
            config: {},
            item: {},
        };
    }

    render() {
        if (!this.hass) {
            return html``;
        }

        const item = this.item || {};

        return html`
            <ha-card header="${item.id ? 'Modifica Articolo' : 'Aggiungi Articolo'}">
                <div class="card-content">
                    <paper-input
                        label="Nome"
                        .value=${item.name || ''}
                        @value-changed=${e => this._valueChanged('name', e.detail.value)}
                    ></paper-input>
                    <paper-input
                        label="Quantità"
                        type="number"
                        .value=${item.quantity || ''}
                        @value-changed=${e => this._valueChanged('quantity', e.detail.value)}
                    ></paper-input>
                    <paper-input
                        label="Unità"
                        .value=${item.unit || ''}
                        @value-changed=${e => this._valueChanged('unit', e.detail.value)}
                    ></paper-input>
                    <paper-input
                        label="Categoria"
                        .value=${item.category || ''}
                        @value-changed=${e => this._valueChanged('category', e.detail.value)}
                    ></paper-input>
                    <ha-date-input
                        label="Data di scadenza"
                        .value=${item.expiration_date || ''}
                        @value-changed=${e => this._valueChanged('expiration_date', e.detail.value)}
                    ></ha-date-input>
                </div>
                <div class="card-actions">
                    <mwc-button @click=${this._close}>Annulla</mwc-button>
                    <mwc-button raised @click=${this._save}>Salva</mwc-button>
                </div>
            </ha-card>
        `;
    }

    _valueChanged(key, value) {
        this.item = { ...this.item, [key]: value };
    }
    
    _close() {
        const event = new Event('close-dialog');
        this.dispatchEvent(event);
    }

    _save() {
        const service = this.item.id ? 'update_item' : 'add_item';
        const serviceData = { ...this.item };
        if (!serviceData.id) {
            delete serviceData.id;
        }

        this.hass.callService("planmydinner", service, serviceData).then(() => {
            this._close();
        });
    }
    
    static get styles() {
        return css`
            .card-content {
                display: flex;
                flex-direction: column;
                gap: 16px;
            }
            .card-actions {
                display: flex;
                justify-content: flex-end;
                padding: 8px;
            }
        `;
    }
}

customElements.define("planmydinner-pantry-item-card", PlanMyDinnerPantryItemCard);
