import { mount } from '@vue/test-utils';
import Pantry from '../../pantry.js';

describe('Pantry', () => {
    
    let wrapper;

    beforeEach(() => {
        global.fetch = jest.fn(() =>
            Promise.resolve({
                json: () => Promise.resolve([]),
            })
        );

        wrapper = mount(Pantry);
    });

    it('renders the component', () => {
        expect(wrapper.find('h2').text()).toBe('Pantry');
    });
});
