// Use a robust method to get LitElement from an existing Home Assistant element
// This avoids dependency issues with HACS or path changes.
const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerCard extends LitElement {
  static get properties() {
    return {
      hass: {},
      config: {},
    };
  }

  // Helper function to call the planmydinner services
  _callService(service, serviceData) {
    this.hass.callService("planmydinner", service, serviceData);
  }

  // Main render function
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
        <ha-card header="Plan My Dinner">
          <div class="card-content">
            Entity <strong>${entityId}</strong> not found. Please check your configuration.
          </div>
        </ha-card>
      `;
    }

    const lunch = state.attributes.lunch;
    const dinner = state.attributes.dinner;

    return html`
      <ha-card header="Piano del Giorno">
        <div class="meal-section">
          <div class="meal-header">
            <h2>Pranzo</h2>
          </div>
          ${lunch
            ? this._renderMeal(lunch, 'lunch')
            : html`<div class="card-content"><p>Nessun pasto pianificato.</p></div>`}
        </div>
        <div class="meal-section">
          <div class="meal-header">
            <h2>Cena</h2>
          </div>
          ${dinner
            ? this._renderMeal(dinner, 'dinner')
            : html`<div class="card-content"><p>Nessun pasto pianificato.</p></div>`}
        </div>
      </ha-card>
    `;
  }

  // Renders the details for a single meal
  _renderMeal(meal, mealType) {
    return html`
      <div class="card-content">
        <div class="meal-info">
          <p class="recipe-name">${meal.recipe_name || 'Ricetta non specificata'}</p>
          <!-- In future, more details like dose and time will go here -->
        </div>
        <div class="actions">
          <mwc-button raised @click=${() => this._handleConsumed(mealType, meal, false)}>
            CONFERMA PASTO
          </mwc-button>
          <mwc-button @click=${() => this._handleConsumed(mealType, meal, true)}>
            HO MANGIATO ALTRO
          </mwc-button>
        </div>
      </div>
    `;
  }

  // Handles button clicks to call the correct service
  _handleConsumed(mealType, meal, isOverride) {
    if (isOverride) {
      // Per l'MVP, usiamo un semplice prompt. In futuro diventerà un modale.
      const overrideText = prompt(`Cosa hai mangiato a ${mealType} al posto di ${meal.recipe_name}?`);
      if (overrideText) {
        this._callService("override_consumed", {
          meal_type: mealType,
          free_text: overrideText,
        });
      }
    } else {
      // Chiamiamo il servizio per confermare il pasto consumato
      this._callService("mark_consumed", {
        recipe_id: meal.recipe_id,
        meal_type: mealType,
      });
    }
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("You need to define an entity");
    }
    this.config = config;
  }

  getCardSize() {
    // This can be calculated dynamically based on content in the future
    return 5;
  }

  static get styles() {
    return css`
      .meal-section {
        border-bottom: 1px solid var(--divider-color);
      }
      .meal-section:last-child {
        border-bottom: none;
      }
      .meal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 16px;
      }
      .meal-header h2 {
          margin: 0.8em 0;
      }
      .recipe-name {
        font-size: 1.2em;
        font-weight: 500;
        margin-top: 0;
      }
      .actions {
        display: flex;
        justify-content: flex-end;
        padding-top: 8px;
        padding-right: 8px;
      }
      mwc-button {
        margin-left: 8px;
      }
    `;
  }
}

customElements.define("planmydinner-card", PlanMyDinnerCard);
