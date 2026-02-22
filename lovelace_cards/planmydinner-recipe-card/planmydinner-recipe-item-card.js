const LitElement = Object.getPrototypeOf(customElements.get("hui-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class PlanMyDinnerRecipeItemCard extends LitElement {
    static get properties() {
        return {
            hass: {},
            config: {},
            recipe: {},
            read_only: { type: Boolean },
        };
    }

    render() {
        if (!this.hass) {
            return html``;
        }

        const recipe = this.recipe || {};
        const readOnly = this.read_only || false;

        return html`
            <ha-card header="${recipe.id && !readOnly ? 'Modifica Ricetta' : recipe.id ? recipe.name : 'Aggiungi Ricetta'}">
                <div class="card-content">
                    <paper-input
                        label="Nome"
                        .value=${recipe.name || ''}
                        @value-changed=${e => this._valueChanged('name', e.detail.value)}
                        .disabled=${readOnly}
                    ></paper-input>
                    <paper-input
                        label="Descrizione"
                        .value=${recipe.description || ''}
                        @value-changed=${e => this._valueChanged('description', e.detail.value)}
                        .disabled=${readOnly}
                    ></paper-input>
                    
                    <h3>Ingredienti</h3>
                    ${(recipe.ingredients || []).map((ingredient, index) => html`
                        <div class="ingredient">
                            <paper-input
                                .value=${ingredient.name}
                                @value-changed=${e => this._ingredientChanged(index, 'name', e.detail.value)}
                                .disabled=${readOnly}
                            ></paper-input>
                            ${!readOnly ? html`<mwc-icon-button icon="mdi:delete" @click=${() => this._removeIngredient(index)}></mwc-icon-button>` : ''}
                        </div>
                    `)}
                    ${!readOnly ? html`<mwc-button @click=${this._addIngredient}>Aggiungi Ingrediente</mwc-button>`: ''}
                    
                    <h3>Procedimento</h3>
                    ${(recipe.steps || []).map((step, index) => html`
                        <div class="step">
                            <paper-input
                                .value=${step}
                                @value-changed=${e => this._stepChanged(index, e.detail.value)}
                                .disabled=${readOnly}
                            ></paper-input>
                            ${!readOnly ? html`<mwc-icon-button icon="mdi:delete" @click=${() => this._removeStep(index)}></mwc-icon-button>` : ''}
                        </div>
                    `)}
                    ${!readOnly ? html`<mwc-button @click=${this._addStep}>Aggiungi Passaggio</mwc-button>` : ''}

                </div>
                <div class="card-actions">
                    <mwc-button @click=${this._close}>Chiudi</mwc-button>
                    ${!readOnly ? html`<mwc-button raised @click=${this._save}>Salva</mwc-button>` : ''}
                </div>
            </ha-card>
        `;
    }

    _valueChanged(key, value) {
        if (this.read_only) return;
        this.recipe = { ...this.recipe, [key]: value };
    }

    _ingredientChanged(index, key, value) {
        if (this.read_only) return;
        const ingredients = [...(this.recipe.ingredients || [])];
        ingredients[index] = { ...ingredients[index], [key]: value };
        this.recipe = { ...this.recipe, ingredients };
    }

    _addIngredient() {
        if (this.read_only) return;
        const ingredients = [...(this.recipe.ingredients || []), { name: '' }];
        this.recipe = { ...this.recipe, ingredients };
    }

    _removeIngredient(index) {
        if (this.read_only) return;
        const ingredients = [...(this.recipe.ingredients || [])];
        ingredients.splice(index, 1);
        this.recipe = { ...this.recipe, ingredients };
    }

    _stepChanged(index, value) {
        if (this.read_only) return;
        const steps = [...(this.recipe.steps || [])];
        steps[index] = value;
        this.recipe = { ...this.recipe, steps };
    }
    
    _addStep() {
        if (this.read_only) return;
        const steps = [...(this.recipe.steps || []), ''];
        this.recipe = { ...this.recipe, steps };
    }

    _removeStep(index) {
        if (this.read_only) return;
        const steps = [...(this.recipe.steps || [])];
        steps.splice(index, 1);
        this.recipe = { ...this.recipe, steps };
    }
    
    _close() {
        const event = new Event('close-dialog');
        this.dispatchEvent(event);
    }

    _save() {
        if (this.read_only) return;
        const service = this.recipe.id ? 'update_recipe' : 'add_recipe';
        const serviceData = { ...this.recipe };
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
            .ingredient, .step {
                display: flex;
                align-items: center;
            }
            .ingredient paper-input, .step paper-input {
                flex-grow: 1;
            }
        `;
    }
}

customElements.define("planmydinner-recipe-item-card", PlanMyDinnerRecipeItemCard);
