const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerWeekCard extends LitElement {
    static get properties() {
        return {
            hass: {},
            config: {},
        };
    }

    setConfig(config) {
        if (!config.plan_entity) {
            throw new Error("You need to define a plan_entity");
        }
        if (!config.recipes_entity) {
            throw new Error("You need to define a recipes_entity");
        }
        this.config = config;
    }

    getCardSize() {
        return 7;
    }

    render() {
        if (!this.hass || !this.config) {
            return html``;
        }

        const planEntityId = this.config.plan_entity;
        if (!planEntityId) {
            return html`
                <ha-card>
                    <div class="card-content">Error: You must define a plan_entity in the card configuration.</div>
                </ha-card>
            `;
        }
        const planState = this.hass.states[planEntityId];

        if (!planState) {
            return html`
                <ha-card header="Piano Settimanale">
                    <div class="card-content">
                        Entity <strong>${planEntityId}</strong> not found. Please check your configuration.
                    </div>
                </ha-card>
            `;
        }
        
        const recipesEntityId = this.config.recipes_entity;
        if (!recipesEntityId) {
            return html`
                <ha-card>
                    <div class="card-content">Error: You must define a recipes_entity in the card configuration.</div>
                </ha-card>
            `;
        }
        const recipesState = this.hass.states[recipesEntityId];
        
        if (!recipesState) {
            return html`
                <ha-card header="Piano Settimanale">
                    <div class="card-content">
                        Entity <strong>${recipesEntityId}</strong> not found. Please check your configuration.
                    </div>
                </ha-card>
            `;
        }

        const weeklyPlan = planState.attributes.weekly_plan || [];
        const recipes = recipesState.attributes.recipes || [];

        return html`
            <ha-card header="Piano Settimanale">
                <div class="week-grid">
                    ${weeklyPlan.map(day => this._renderDay(day, recipes))}
                </div>
                <div class="card-actions">
                    <mwc-button raised @click=${this._regenerateWeek}>RIGENERA SETTIMANA</mwc-button>
                </div>
            </ha-card>
        `;
    }

    _renderDay(day, recipes) {
        const lunch = day.meals.find(m => m.meal_type === 'lunch');
        const dinner = day.meals.find(m => m.meal_type === 'dinner');

        const lunchRecipe = lunch ? recipes.find(r => r.id === lunch.recipe_id) : null;
        const dinnerRecipe = dinner ? recipes.find(r => r.id === dinner.recipe_id) : null;

        return html`
            <div class="day">
                <h4>${new Date(day.date).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric' })}</h4>
                <div class="meal" @click=${() => this._showRecipe(lunchRecipe)}>
                    <strong>Pranzo:</strong> ${lunchRecipe ? lunchRecipe.name : 'N/A'}
                </div>
                <div class="meal" @click=${() => this._showRecipe(dinnerRecipe)}>
                    <strong>Cena:</strong> ${dinnerRecipe ? dinnerRecipe.name : 'N/A'}
                </div>
            </div>
        `;
    }

    _showRecipe(recipe) {
        if (!recipe) {
            return;
        }
        this.hass.callService("browser_mod", "popup", {
            title: recipe.name,
            content: {
                type: "custom:planmydinner-recipe-item-card",
                recipe: recipe,
                read_only: true, // I need to implement this in the item card
            },
        });
    }
    
    _regenerateWeek() {
        this.hass.callService("planmydinner", "generate_week", {
            // These should be configurable
            profile_id_A: 'persona_a',
            profile_id_B: 'persona_b',
            current_date: new Date().toISOString().slice(0, 10),
        });
    }

    static get styles() {
        return css`
            .week-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 16px;
                padding: 16px;
            }
            .day {
                border: 1px solid var(--divider-color);
                border-radius: 4px;
                padding: 8px;
            }
            .day h4 {
                margin: 0 0 8px;
                text-align: center;
            }
            .meal {
                padding: 4px;
                cursor: pointer;
            }
            .meal:hover {
                background-color: var(--secondary-background-color);
            }
            .card-actions {
                display: flex;
                justify-content: flex-end;
                padding: 8px;
            }
        `;
    }
}

customElements.define("planmydinner-week-card", PlanMyDinnerWeekCard);
