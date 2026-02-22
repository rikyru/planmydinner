import "./planmydinner-recipe-item-card.js";

const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerRecipeCard extends LitElement {
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
                <ha-card header="Ricette">
                    <div class="card-content">
                        Entity <strong>${entityId}</strong> not found. Please check your configuration.
                    </div>
                </ha-card>
            `;
        }

        const recipes = state.attributes.recipes || [];

        return html`
            <ha-card header="Ricette">
                <div class="card-content">
                    ${recipes.map(recipe => this._renderRecipe(recipe))}
                </div>
                <div class="card-actions">
                    <mwc-button raised @click=${() => this._editRecipe()}>AGGIUNGI RICETTA</mwc-button>
                </div>
            </ha-card>
        `;
    }

    _renderRecipe(recipe) {
        return html`
            <div class="recipe">
                <div class="recipe-info">
                    <h3>${recipe.name}</h3>
                    <p>${recipe.description}</p>
                </div>
                <div class="recipe-actions">
                    <mwc-icon-button icon="mdi:pencil" @click=${() => this._editRecipe(recipe)}></mwc-icon-button>
                    <mwc-icon-button icon="mdi:delete" @click=${() => this._removeRecipe(recipe.id)}></mwc-icon-button>
                </div>
            </div>
        `;
    }

    _editRecipe(recipe = {}) {
        this.hass.callService("browser_mod", "popup", {
            title: recipe.id ? "Modifica Ricetta" : "Aggiungi Ricetta",
            content: {
                type: "custom:planmydinner-recipe-item-card",
                recipe: recipe,
            },
        });
    }

    _removeRecipe(recipeId) {
        if (confirm("Sei sicuro di voler rimuovere questa ricetta?")) {
            this.hass.callService("planmydinner", "delete_recipe", { recipe_id: recipeId });
        }
    }

    static get styles() {
        return css`
            .recipe {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid var(--divider-color);
                padding: 8px 0;
            }
            .recipe:last-child {
                border-bottom: none;
            }
            .recipe-info {
                flex-grow: 1;
            }
            .recipe-info h3 {
                margin: 0;
            }
            .recipe-info p {
                margin: 4px 0 0;
                color: var(--secondary-text-color);
            }
            .card-actions {
                display: flex;
                justify-content: flex-end;
                padding: 8px;
            }
        `;
    }
}

customElements.define("planmydinner-recipe-card", PlanMyDinnerRecipeCard);
