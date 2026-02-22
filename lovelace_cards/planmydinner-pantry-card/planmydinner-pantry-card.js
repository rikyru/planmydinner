import "./planmydinner-pantry-item-card.js";
const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerPantryCard extends LitElement {
  static get properties() {
    return {
      hass: {},
      config: {},
    };
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
        <ha-card header="Pantry">
          <div class="card-content">
            Entity <strong>${entityId}</strong> not found. Please check your configuration.
          </div>
        </ha-card>
      `;
    }

    const items = state.attributes.items || [];

    return html`
      <ha-card header="Dispensa">
        <div class="card-content">
          <table>
            <thead>
              <tr>
                <th>Articolo</th>
                <th>Quantità</th>
                <th>Scadenza</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${items.map(item => this._renderItem(item))}
            </tbody>
          </table>
        </div>
        <div class="card-actions">
            <mwc-button raised @click=${() => this._editItem()}>AGGIUNGI ARTICOLO</mwc-button>
        </div>
      </ha-card>
    `;
  }

  _renderItem(item) {
    const isExpiring = this._isExpiring(item.expiration_date);
    return html`
      <tr class=${isExpiring ? 'expiring' : ''}>
        <td>${item.name}</td>
        <td>${item.quantity} ${item.unit}</td>
        <td>${item.expiration_date}</td>
        <td>
          <mwc-icon-button icon="mdi:pencil" @click=${() => this._editItem(item)}></mwc-icon-button>
          <mwc-icon-button icon="mdi:delete" @click=${() => this._removeItem(item.id)}></mwc-icon-button>
        </td>
      </tr>
    `;
  }

  _isExpiring(dateStr) {
    if (!dateStr) {
        return false;
    }
    const expDate = new Date(dateStr);
    const today = new Date();
    const diffTime = expDate.getTime() - today.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays >= 0 && diffDays <= 7;
  }

  _editItem(item = {}) {
    this.hass.callService("browser_mod", "popup", {
      title: item.id ? "Modifica Articolo" : "Aggiungi Articolo",
      content: {
        type: "custom:planmydinner-pantry-item-card",
        item: item,
      },
    });
  }

  _callService(service, serviceData) {
    this.hass.callService("planmydinner", service, serviceData);
  }

  _removeItem(itemId) {
    if (confirm("Sei sicuro di voler rimuovere questo articolo?")) {
        this._callService("remove_item", { item_id: itemId });
    }
  }

  static get styles() {
    return css`
      .expiring {
        background-color: var(--warning-color, #ff9800);
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th, td {
        padding: 8px;
        text-align: left;
        border-bottom: 1px solid var(--divider-color);
      }
      .card-actions {
        display: flex;
        justify-content: flex-end;
        padding: 8px;
      }
    `;
  }
}

customElements.define("planmydinner-pantry-card", PlanMyDinnerPantryCard);
