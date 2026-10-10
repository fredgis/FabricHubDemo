import type { CampaignImpact } from './campaignImpact';

export type CampaignMoney = (minor: string | null) => string;
export type ContributionGroup = 'films' | 'genres' | 'distributors';

/** The API's exponent is authoritative; only relative chart widths use Number. */
export function campaignMoney(currency: string, exponent: number | undefined): CampaignMoney {
  if (exponent === undefined) return () => 'Not available';
  const format = new Intl.NumberFormat('en', {
    style: 'currency', currency, minimumFractionDigits: exponent, maximumFractionDigits: exponent,
  });
  const divisor = 10n ** BigInt(exponent);
  return minor => {
    if (minor === null) return 'Not available';
    const exact = BigInt(minor);
    const magnitude = exact < 0n ? -exact : exact;
    const fraction = (magnitude % divisor).toString().padStart(exponent, '0');
    const amount = format.formatToParts(magnitude / divisor)
      .map(part => part.type === 'fraction' ? fraction : part.value).join('');
    return exact < 0n ? `-${amount}` : amount;
  };
}

export function largestMinor(values: (string | null)[]): string {
  return values.reduce<bigint>((largest, value) => {
    const exact = BigInt(value ?? '0');
    return exact > largest ? exact : largest;
  }, 0n).toString();
}

export function titleContributions(titles: CampaignImpact['titles'], group: ContributionGroup) {
  const rows = new Map<string, { key: string; name: string; detail: string; bookedMinor: string; engagedMinor: string }>();
  for (const title of titles) {
    const key = group === 'films' ? title.content_key : group === 'genres' ? title.genre : title.distributor;
    const current = rows.get(key);
    rows.set(key, {
      key,
      name: group === 'films' ? title.title : key || (group === 'genres' ? 'Genre not recorded' : 'Distributor not recorded'),
      detail: group === 'films' ? `${title.genre || 'Genre not recorded'} · ${title.distributor || 'Distributor not recorded'}` : '',
      bookedMinor: (BigInt(current?.bookedMinor ?? '0') + BigInt(title.booked_minor)).toString(),
      engagedMinor: (BigInt(current?.engagedMinor ?? '0') + BigInt(title.engaged_minor)).toString(),
    });
  }
  return [...rows.values()].sort((left, right) => {
    const difference = BigInt(right.engagedMinor) - BigInt(left.engagedMinor);
    return difference > 0n ? 1 : difference < 0n ? -1 : left.name.localeCompare(right.name);
  });
}
