import { mount } from '@vue/test-utils';
import sidebarSource from '@/components/Sidebar.vue?raw';
import { describe, expect, it } from 'vitest';
import ProductMap from '@/components/ProductMap.vue';
import DemoUpgradeModal from '@/components/DemoUpgradeModal.vue';
import { openDemoUpgradeModal } from '@/composables/demoModeState';

describe('product guidance and accessible actions', () => {
  it('uses the same product map in Documentation and the compact Demo banner', () => {
    const full = mount(ProductMap);
    expect(full.findAll('dt').map(node => node.text())).toEqual(['OSS', 'Demo', 'Pro']);
    expect(full.text()).toContain('Local compute');
    const compact = mount(ProductMap, { props: { compact: true } });
    expect(compact.text()).toContain('Demo · Hosted evaluation');
    expect(compact.get('a').attributes('href')).toBe(full.get('a').attributes('href'));
  });

  it('provides real links without nested buttons or a placeholder plan link', () => {
    openDemoUpgradeModal({ message: 'Choose a plan', upgradeUrl: '', availablePlans: [] });
    const view = mount(DemoUpgradeModal, { global: { stubs: {
      Dialog: { template: '<div><slot /><slot name="footer" /></div>' },
      Button: true, Tag: true,
    } } });
    expect(view.find('a button').exists()).toBe(false);
    expect(view.find('a[href="#"]').exists()).toBe(false);
    expect(view.get('a').text()).toContain('View Docs');
    view.unmount();
  });

  it('keeps inactive sidebar text above 4.5:1 contrast, including hover', () => {
    const source = sidebarSource;
    const luminance = (hex: string) => {
      const rgb = hex.match(/[0-9a-f]{2}/g)!.map(part => parseInt(part, 16) / 255)
        .map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    for (const color of ['475569', '64748b', '6504bd']) {
      expect((luminance('fefbff') + 0.05) / (luminance(color) + 0.05)).toBeGreaterThanOrEqual(4.5);
    }
    expect(source).toMatch(/\.nav-link\s*\{[^}]*color: #475569/s);
    expect(source).toMatch(/\.nav-link.secondary:hover\s*\{[^}]*color: #6504bd/s);
    expect(source).not.toMatch(/\.nav-dimmed\s*\{[^}]*opacity:/s);
  });
});
