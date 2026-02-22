import { mount, flushPromises } from '@vue/test-utils';
import ImportWizard from '../../import.js';

describe('ImportWizard', () => {
    
    let wrapper;

    beforeEach(() => {
        wrapper = mount(ImportWizard);
    });

    it('renders the component', () => {
        expect(wrapper.find('h2').text()).toBe('Import Wizard');
    });

    it('shows the review and edit UI after a successful upload', async () => {
        const mockFile = new File(['file content'], 'test.pdf', { type: 'application/pdf' });
        const mockPlan = {
            daily_plans: [
                {
                    date: '2026-02-21',
                    meals: [
                        {
                            meal_type: 'pranzo',
                            items: [
                                { item_name: 'Riso', quantity: 80, unit: 'g' }
                            ]
                        }
                    ]
                }
            ]
        };
        global.fetch = jest.fn(() =>
            Promise.resolve({
                json: () => Promise.resolve(mockPlan),
            })
        );
        
        const fileInput = wrapper.find('input[type="file"]');
        Object.defineProperty(fileInput.element, 'files', {
            value: [mockFile],
            writable: true,
        });
        await fileInput.trigger('change');
        await wrapper.find('button').trigger('click');

        await flushPromises();

        expect(wrapper.find('h3').text()).toBe('Review and Edit');
    });
});
