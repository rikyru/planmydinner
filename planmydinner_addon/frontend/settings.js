import { defineComponent } from 'vue';

const SettingsView = defineComponent({
    name: 'SettingsView',
    inject: ['toast'],
    template: `
        <div class="settings-view">
            <h2>Impostazioni</h2>

            <!-- ── Sezione 1: Configurazione LLM ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">🤖 Configurazione LLM</h3>
                <div class="settings-section__body">
                    <div class="settings-field">
                        <label>Provider</label>
                        <select v-model="config.llm_provider">
                            <option value="openai">OpenAI (GPT)</option>
                            <option value="ollama">Ollama (locale)</option>
                        </select>
                    </div>

                    <div class="settings-field">
                        <label>Modello</label>
                        <input v-model="config.llm_model" type="text"
                               :placeholder="config.llm_provider === 'openai' ? 'es. gpt-4o-mini' : 'es. llama3'">
                    </div>

                    <div class="settings-field">
                        <label>Chiave API
                            <span v-if="hasApiKey" class="settings-key-badge">✓ Configurata</span>
                        </label>
                        <input v-model="config.llm_api_key" type="password"
                               placeholder="Lascia vuoto per non modificarla"
                               autocomplete="new-password">
                        <span class="settings-hint" v-if="config.llm_provider === 'ollama'">
                            Non necessaria per Ollama locale.
                        </span>
                    </div>

                    <div class="settings-field" v-if="config.llm_provider === 'ollama'">
                        <label>Base URL</label>
                        <input v-model="config.llm_base_url" type="text"
                               placeholder="es. http://localhost:11434">
                    </div>

                    <div class="settings-field">
                        <label>Temperature: <strong>{{ (config.llm_temperature || 0.7).toFixed(1) }}</strong></label>
                        <div class="temperature-row">
                            <input type="range" v-model.number="config.llm_temperature"
                                   min="0.1" max="1.5" step="0.1" style="flex:1">
                            <span class="settings-hint" style="white-space:nowrap">
                                0.1 = conservativo · 1.5 = creativo
                            </span>
                        </div>
                    </div>

                    <button class="btn-primary" @click="saveConfig" :disabled="savingConfig">
                        {{ savingConfig ? 'Salvataggio...' : 'Salva configurazione' }}
                    </button>
                </div>
            </div>

            <!-- ── Sezione 2: Regole personalizzate LLM ── -->
            <div class="settings-section">
                <h3 class="settings-section__title">📝 Regole personalizzate per la generazione</h3>
                <div class="settings-section__body">
                    <p class="settings-hint">
                        Queste regole vengono aggiunte ad ogni richiesta alla LLM durante la generazione dei pasti.
                        Usale per personalizzare lo stile culinario, preferenze regionali, ingredienti da favorire o evitare.
                    </p>
                    <div class="settings-field">
                        <label>Regole (una per riga)</label>
                        <textarea v-model="config.llm_custom_rules" rows="8"
                                  placeholder="- Preferisci ricette della cucina siciliana&#10;- Usa spesso aglio, olio d'oliva e pomodoro&#10;- Evita il cous cous, preferisci farro o orzo&#10;- I piatti devono essere semplici da preparare in 20 minuti&#10;- Usa erbe aromatiche (basilico, rosmarino, timo)"></textarea>
                    </div>
                    <button class="btn-primary" @click="saveRules" :disabled="savingRules">
                        {{ savingRules ? 'Salvataggio...' : 'Salva regole' }}
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            config: {
                llm_provider: 'openai',
                llm_model: '',
                llm_api_key: '',
                llm_base_url: '',
                llm_temperature: 0.7,
                llm_custom_rules: '',
            },
            hasApiKey: false,
            savingConfig: false,
            savingRules: false,
        };
    },
    mounted() {
        this.loadSettings();
    },
    methods: {
        async loadSettings() {
            try {
                const resp = await fetch('/settings/');
                if (!resp.ok) return;
                const data = await resp.json();
                this.hasApiKey = data.has_api_key || false;
                this.config.llm_provider = data.llm_provider || 'openai';
                this.config.llm_model = data.llm_model || '';
                this.config.llm_base_url = data.llm_base_url || '';
                this.config.llm_temperature = data.llm_temperature || 0.7;
                this.config.llm_custom_rules = data.llm_custom_rules || '';
                // api_key is never returned — keep field empty
            } catch (e) {
                this.toast.add('Errore nel caricamento impostazioni', 'error');
            }
        },
        async saveConfig() {
            this.savingConfig = true;
            try {
                const body = {
                    llm_provider: this.config.llm_provider,
                    llm_model: this.config.llm_model,
                    llm_base_url: this.config.llm_base_url,
                    llm_temperature: this.config.llm_temperature,
                };
                // Only send api_key if user typed something
                if (this.config.llm_api_key && this.config.llm_api_key.trim()) {
                    body.llm_api_key = this.config.llm_api_key.trim();
                }
                const resp = await fetch('/settings/', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio');
                const data = await resp.json();
                this.hasApiKey = data.has_api_key || false;
                this.config.llm_api_key = '';  // clear after save
                this.toast.add('Configurazione LLM salvata', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingConfig = false;
            }
        },
        async saveRules() {
            this.savingRules = true;
            try {
                const resp = await fetch('/settings/', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ llm_custom_rules: this.config.llm_custom_rules }),
                });
                if (!resp.ok) throw new Error('Errore nel salvataggio');
                this.toast.add('Regole LLM salvate', 'success');
            } catch (e) {
                this.toast.add('Errore: ' + e.message, 'error');
            } finally {
                this.savingRules = false;
            }
        },
    },
});

export default SettingsView;
