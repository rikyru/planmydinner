import { defineComponent } from 'vue';

const Recipes = defineComponent({
    template: `
        <div>
            <h2>Recipes</h2>
            <div v-for="recipe in recipes" :key="recipe.id" class="recipe">
                <h3>{{ recipe.name }}</h3>
                <p>{{ recipe.description }}</p>
                <button @click="editRecipe(recipe)">Edit</button>
                <button @click="deleteRecipe(recipe.id)">Delete</button>
            </div>
            <button @click="addRecipe">Add Recipe</button>

            <div class="modal" v-if="showModal">
                <div class="modal-content">
                    <h3>{{ editedRecipe.id ? 'Edit Recipe' : 'Add Recipe' }}</h3>
                    <input v-model="editedRecipe.name" placeholder="Name">
                    <textarea v-model="editedRecipe.description" placeholder="Description"></textarea>
                    
                    <h4>Ingredients</h4>
                    <div v-for="(ingredient, index) in editedRecipe.ingredients" :key="index">
                        <input v-model="ingredient.name" placeholder="Ingredient Name">
                        <button @click="removeIngredient(index)">Remove</button>
                    </div>
                    <button @click="addIngredient">Add Ingredient</button>

                    <h4>Steps</h4>
                    <div v-for="(step, index) in editedRecipe.steps" :key="index">
                        <input v-model="editedRecipe.steps[index]" placeholder="Step description">
                        <button @click="removeStep(index)">Remove</button>
                    </div>
                    <button @click="addStep">Add Step</button>

                    <button @click="saveRecipe">Save</button>
                    <button @click="closeModal">Cancel</button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            recipes: [],
            showModal: false,
            editedRecipe: { ingredients: [], steps: [] },
        }
    },
    methods: {
        fetchRecipes() {
            fetch('/recipes')
                .then(response => response.json())
                .then(data => {
                    this.recipes = data;
                });
        },
        addRecipe() {
            this.editedRecipe = { ingredients: [], steps: [] };
            this.showModal = true;
        },
        editRecipe(recipe) {
            this.editedRecipe = JSON.parse(JSON.stringify(recipe)); // Deep copy
            if (!this.editedRecipe.ingredients) this.editedRecipe.ingredients = [];
            if (!this.editedRecipe.steps) this.editedRecipe.steps = [];
            this.showModal = true;
        },
        closeModal() {
            this.showModal = false;
        },
        addIngredient() {
            this.editedRecipe.ingredients.push({ name: '' });
        },
        removeIngredient(index) {
            this.editedRecipe.ingredients.splice(index, 1);
        },
        addStep() {
            this.editedRecipe.steps.push('');
        },
        removeStep(index) {
            this.editedRecipe.steps.splice(index, 1);
        },
        saveRecipe() {
            const method = this.editedRecipe.id ? 'PUT' : 'POST';
            const url = this.editedRecipe.id ? `/recipes/${this.editedRecipe.id}` : '/recipes';

            fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.editedRecipe),
            })
            .then(() => {
                this.fetchRecipes();
                this.closeModal();
            });
        },
        deleteRecipe(recipeId) {
            fetch(`/recipes/${recipeId}`, { method: 'DELETE' })
                .then(() => {
                    this.fetchRecipes();
                });
        }
    },
    mounted() {
        this.fetchRecipes();
    }
});

export default Recipes;
