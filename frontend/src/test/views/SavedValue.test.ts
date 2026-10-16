import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import SavedValue from '@/views/models/SavedValue.vue';

describe('retained scientific tables', () => {
  it('shows peak measurements as labelled rows while keeping constituent detections expandable', () => {
    const wrapper = mount(SavedValue, { props: { value: {
      input_type: 'PeakFinding', summary: { n_peaks: 2 }, data: [
        { peak: 1, position: 1200.5, detection_count: 3, constituent_detections: [{ sample: 'A', position: 1200.4 }] },
        { peak: 2, position: 1450.2, detection_count: 2, constituent_detections: [] },
      ],
    } } });
    expect(wrapper.findAll('tbody tr')).toHaveLength(2);
    expect(wrapper.get('thead').text()).toContain('detection count');
    expect(wrapper.get('tbody').text()).toContain('1200.5');
    expect(wrapper.get('tbody').text()).toContain('1450.2');
    expect(wrapper.findAll('tbody details')).toHaveLength(2);
  });
  it('does not fabricate rows for a scalar diagnostic record', () => {
    const wrapper = mount(SavedValue, { props: { value: { rmse: 1.2949488617445029, n_samples: 231 } } });
    expect(wrapper.find('table').exists()).toBe(false);
    expect(wrapper.text()).toContain('1.2949488617445029');
  });
});
