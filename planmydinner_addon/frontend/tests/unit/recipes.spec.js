import { mount } from '@vue/test-utils';
import Recipes from '../../recipes.js';

describe('Recipes', () => {
    
    let wrapper;

    beforeEach(() => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                json: () => Promise.resolve([]),
            })
        );

        wrapper = mount(Recipes);
    });

    it('renders the component', () => {
        expect(wrapper.find('h2').text()).toBe('Recipes');
    });
});
