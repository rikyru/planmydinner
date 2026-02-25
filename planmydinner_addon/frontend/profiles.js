import { defineComponent } from 'vue';

const Profiles = defineComponent({
    template: `
        <div>
            <h2>User Profiles</h2>
            
            <div class="create-profile">
                <h3>Create New Profile</h3>
                <input v-model="newProfileId" placeholder="Profile ID (e.g., user_a)">
                <input v-model="newProfileName" placeholder="Profile Name (e.g., Alice)">
                <button @click="createProfile" :disabled="!newProfileId || !newProfileName">Create</button>
            </div>

            <div class="profile-list">
                <h3>Existing Profiles</h3>
                <ul>
                    <li v-for="profile in profiles" :key="profile.id">
                        <strong>{{ profile.name }}</strong> (ID: {{ profile.id }})
                    </li>
                </ul>
                <p v-if="!profiles.length">No profiles found. Create one above.</p>
            </div>
        </div>
    `,
    data() {
        return {
            profiles: [],
            newProfileId: '',
            newProfileName: '',
        };
    },
    mounted() {
        this.fetchProfiles();
    },
    methods: {
        fetchProfiles() {
            fetch('/profiles')
                .then(response => response.json())
                .then(data => {
                    this.profiles = data;
                })
                .catch(error => console.error('Error fetching profiles:', error));
        },
        createProfile() {
            const newProfile = {
                id: this.newProfileId,
                name: this.newProfileName,
            };

            fetch('/profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newProfile),
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.detail) });
                }
                return response.json();
            })
            .then(() => {
                this.newProfileId = '';
                this.newProfileName = '';
                this.fetchProfiles(); // Refresh the list
            })
            .catch(error => {
                console.error('Error creating profile:', error);
                alert('Failed to create profile: ' + error.message);
            });
        },
    },
});

export default Profiles;
