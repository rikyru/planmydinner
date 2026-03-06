/**
 * Plan My Dinner - Lovelace Custom Card
 * Shows today's pranzo + cena, shopping count, and a link to the full UI.
 *
 * Usage in Lovelace YAML:
 *   type: custom:planmydinner-card
 *   title: "Pasti di oggi"          # optional
 */

class PlanMyDinnerCard extends HTMLElement {
  set hass(hass) {
    if (!this.shadowRoot) return;
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = config;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }
    this._render();
  }

  _getSensorState(entityId) {
    const hass = this._hass;
    if (!hass || !hass.states[entityId]) return null;
    return hass.states[entityId];
  }

  _findEntity(suffix) {
    if (!this._hass) return null;
    const key = Object.keys(this._hass.states).find(id =>
      id.startsWith('sensor.plan_my_dinner_') && id.endsWith(suffix)
    );
    return key ? this._hass.states[key] : null;
  }

  _render() {
    if (!this.shadowRoot) return;

    const title = (this._config && this._config.title) || 'Plan My Dinner';

    const todaySensor = this._findEntity('today');
    const shoppingSensor = this._findEntity('shopping');
    const webUISensor = this._findEntity('web_ui') || this._getSensorState('sensor.plan_my_dinner_web_ui');

    const webUrl = webUISensor ? webUISensor.state : null;

    let pranzo = '—';
    let cena = '—';
    if (todaySensor && todaySensor.attributes && todaySensor.attributes.meals) {
      const meals = todaySensor.attributes.meals;
      if (meals.pranzo && meals.pranzo.length) pranzo = meals.pranzo.join(', ');
      if (meals.cena && meals.cena.length) cena = meals.cena.join(', ');
    } else if (todaySensor && todaySensor.state && todaySensor.state !== 'no_plan') {
      pranzo = todaySensor.state;
    }

    const shoppingCount = shoppingSensor ? shoppingSensor.state : '?';

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card {
          padding: 16px;
          font-family: var(--primary-font-family, sans-serif);
        }
        .title {
          font-size: 1.1em;
          font-weight: 600;
          margin-bottom: 12px;
          color: var(--primary-text-color);
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .meal-row {
          display: flex;
          align-items: flex-start;
          margin-bottom: 8px;
          gap: 8px;
        }
        .meal-label {
          font-weight: 500;
          min-width: 60px;
          color: var(--secondary-text-color);
          font-size: 0.85em;
          text-transform: uppercase;
          padding-top: 2px;
        }
        .meal-value {
          color: var(--primary-text-color);
          font-size: 0.95em;
          flex: 1;
        }
        .meal-value.no-plan {
          color: var(--disabled-text-color, #aaa);
          font-style: italic;
        }
        .divider {
          border: none;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          margin: 12px 0;
        }
        .footer {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .shopping-badge {
          background: var(--accent-color, #03a9f4);
          color: white;
          border-radius: 12px;
          padding: 2px 10px;
          font-size: 0.8em;
          font-weight: 500;
        }
        .open-link {
          color: var(--accent-color, #03a9f4);
          text-decoration: none;
          font-size: 0.85em;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .open-link:hover { text-decoration: underline; }
        .no-sensor {
          color: var(--disabled-text-color, #aaa);
          font-size: 0.9em;
          font-style: italic;
        }
      </style>
      <ha-card>
        <div class="title">
          🍽️ ${title}
        </div>
        ${todaySensor ? `
          <div class="meal-row">
            <span class="meal-label">Pranzo</span>
            <span class="meal-value ${pranzo === '—' ? 'no-plan' : ''}">${pranzo}</span>
          </div>
          <div class="meal-row">
            <span class="meal-label">Cena</span>
            <span class="meal-value ${cena === '—' ? 'no-plan' : ''}">${cena}</span>
          </div>
        ` : `<p class="no-sensor">Sensore "plan_my_dinner_today" non trovato.</p>`}
        <hr class="divider" />
        <div class="footer">
          <span class="shopping-badge">🛒 ${shoppingCount} prodotti</span>
          ${webUrl ? `<a class="open-link" href="${webUrl}" target="_blank">Apri UI ↗</a>` : ''}
        </div>
      </ha-card>
    `;
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    return document.createElement('planmydinner-card-editor');
  }

  static getStubConfig() {
    return { title: 'Plan My Dinner' };
  }
}

customElements.define('planmydinner-card', PlanMyDinnerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'planmydinner-card',
  name: 'Plan My Dinner Card',
  description: 'Shows today\'s meals and links to the full Plan My Dinner UI.',
  preview: false,
});
