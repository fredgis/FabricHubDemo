import { authenticated, boolean, date, entity, int, text, uuid } from '@microsoft/rayfin-core';

// Natural keys are shared with CRM/analytics; UUIDs are Rayfin's entity identifiers.
// All browser data access is read-only. Commands authorize again inside the UDF.
@entity()
@authenticated('read')
export class Content {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) content_key!: string;
  @text({ max: 240 }) title!: string;
  @date() release_date!: Date;
  @int() duration_seconds!: number;
  @text({ max: 80 }) genre!: string;
  @text({ max: 1000 }) image_url!: string;
  @text({ max: 1000 }) source_url!: string;
  @text({ max: 160 }) license!: string;
  @text({ max: 1000 }) attribution!: string;
  @text({ max: 160, optional: true }) metadata_license?: string;
  @text({ max: 40, optional: true }) metadata_date_precision?: string;
  @boolean({ optional: true }) artwork_available?: boolean;
  @text({ max: 160, optional: true }) artwork_license?: string;
  @text({ max: 1000, optional: true }) artwork_source_url?: string;
  @text({ max: 1000, optional: true }) artwork_author?: string;
}

@entity()
@authenticated('read')
export class Customer {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) customer_key!: string;
  @text({ max: 240 }) name!: string;
  @text({ max: 16 }) territory!: string;
}

@entity()
@authenticated('read')
export class Campaign {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) campaign_key!: string;
  @text({ max: 240 }) name!: string;
  @text({ max: 40 }) status!: string;
  @text({ max: 80 }) type!: string;
  @date({ optional: true }) start_date?: Date;
  @date({ optional: true }) end_date?: Date;
}

@entity()
@authenticated('read')
export class CampaignMember {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) member_key!: string;
  @text({ max: 128 }) campaign_key!: string;
  @text({ max: 128 }) customer_key!: string;
  @text({ max: 40 }) status!: string;
}

@entity()
@authenticated('read')
export class IntegrationLink {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) link_key!: string;
  @text({ max: 240 }) name!: string;
  @text({ max: 40 }) type!: string;
  @text({ max: 1000 }) url!: string;
  @text({ max: 400 }) description!: string;
}

@entity()
@authenticated('read')
export class Offer {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) offer_key!: string;
  @text({ max: 128 }) content_key!: string;
  @text({ max: 16 }) territory!: string;
  @text({ max: 3 }) currency!: string;
  @text({ max: 16 }) transaction_type!: string;
  @int() price_minor!: number;
  @int() start_window_hours!: number;
  @int() play_window_hours!: number;
}

@entity()
@authenticated('read')
export class Rental {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) order_id!: string;
  @text({ max: 128 }) customer_key!: string;
  @text({ max: 128 }) offer_key!: string;
  @text({ max: 24 }) status!: string;
  @int() amount_minor!: number;
  @text({ max: 3 }) currency!: string;
  @date() created_at!: Date;
  @date({ optional: true }) start_deadline?: Date;
  @date({ optional: true }) first_play_at?: Date;
  @date({ optional: true }) expires_at?: Date;
}

@entity()
@authenticated('read')
export class Playback {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) session_id!: string;
  @text({ max: 128 }) order_id!: string;
  @text({ max: 128 }) content_key!: string;
  @text({ max: 128 }) customer_key!: string;
  @int() position_seconds!: number;
  @text({ max: 24 }) status!: string;
}

@entity()
@authenticated('read')
export class Outbox {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) event_id!: string;
  @text({ max: 80 }) event_type!: string;
  @int() schema_version!: number;
  @text({ max: 128 }) entity_key!: string;
  @int() source_sequence!: number;
  @date() occurred_at!: Date;
  @date() produced_at!: Date;
  @text({ max: 128 }) run_id!: string;
  @text({ max: 128 }) correlation_id!: string;
  @text({ max: 4000 }) payload!: string;
  @text({ max: 4000 }) payload_json!: string;
  @date({ optional: true }) published_at?: Date;
}

@entity()
@authenticated('read')
export class ControlCommand {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) idempotency_key!: string;
  @text({ max: 24 }) type!: string;
  @text({ max: 24 }) status!: string;
  @text({ max: 2000 }) parameters!: string;
  @date() requested_at!: Date;
  @date({ optional: true }) completed_at?: Date;
  @text({ max: 1000, optional: true }) error?: string;
}

@entity()
@authenticated('read', { policy: (claims, item) => claims.sub.eq(item.user_id) })
export class OperatorGrant {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) user_id!: string;
  @boolean() enabled!: boolean;
  @date() expires_at!: Date;
}

@entity()
@authenticated('read', { policy: (claims, item) => claims.sub.eq(item.user_id) })
export class FlixyAccessGrant {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) user_id!: string;
  @text({ max: 36 }) entra_object_id!: string;
  @text({ max: 36 }) tenant_id!: string;
  @boolean() enabled!: boolean;
}

@entity()
@authenticated('read')
export class RuntimeBinding {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) binding_key!: string;
  @text({ max: 300 }) sql_server!: string;
  @text({ max: 200 }) sql_database!: string;
  @text({ max: 128 }) fabric_item_id!: string;
  @text({ max: 128 }) workspace_id!: string;
  @text({ max: 128 }) capacity_id!: string;
  @boolean() verified!: boolean;
}

@entity()
@authenticated('read', { exclude: ['fingerprint', 'result_json'] })
export class CommandReceipt {
  @uuid() id!: string;
  @text({ max: 128, unique: true }) idempotency_key!: string;
  @text({ max: 64 }) fingerprint!: string;
  @text({ max: 128 }) user_id!: string;
  @text({ max: 4000 }) result_json!: string;
  @date() created_at!: Date;
}

@entity()
@authenticated('read')
export class EventSequence {
  @uuid() id!: string;
  @text({ max: 32, unique: true }) sequence_key!: string;
  @int() value!: number;
}

@entity()
@authenticated('read')
export class VolumeRun {
  @uuid() id!: string;
  @text({ max: 64, unique: true }) run_key!: string;
  @text({ max: 128 }) user_id!: string;
  @text({ max: 64 }) fingerprint!: string;
  @text({ max: 4000 }) profile_json!: string;
  @text({ max: 64 }) source_manifest_hash!: string;
  @text({ max: 64 }) policy_hash!: string;
  @text({ max: 24 }) status!: string;
  @int() total_orders!: number;
  @int() total_events!: number;
  @int() committed_orders!: number;
  @int() committed_events!: number;
  @int() committed_batches!: number;
  @boolean() cancel_requested!: boolean;
  @text({ max: 128, optional: true }) lease_id?: string;
  @date({ optional: true }) lease_expires_at?: Date;
  @date() requested_at!: Date;
  @date() updated_at!: Date;
}

@entity()
@authenticated('read')
export class AnalyticsBinding {
  @uuid() id!: string;
  @text({max:64,unique:true}) binding_key!: string;
  @text({max:160}) name!: string;
  @text({max:300}) sql_server!: string;
  @text({max:128}) sql_database!: string;
  @text({max:128}) item_id!: string;
  @text({max:128}) workspace_id!: string;
  @text({max:128}) capacity_id!: string;
  @boolean() verified!: boolean;
}

@entity()
@authenticated('read')
export class OntologyBinding {
  @uuid() id!:string;
  @text({max:64,unique:true}) binding_key!:string;
  @text({max:128}) workspace_id!:string;
  @text({max:128}) ontology_id!:string;
  @text({max:128}) graph_model_id!:string;
  @text({max:128}) gold_item_id!:string;
  @boolean() verified!:boolean;
}

export type AppSchema = {
  Content: Content; Customer: Customer; Campaign: Campaign; CampaignMember: CampaignMember;
  IntegrationLink: IntegrationLink; Offer: Offer; Rental: Rental;
  Playback: Playback; Outbox: Outbox; ControlCommand: ControlCommand;
  OperatorGrant: OperatorGrant; FlixyAccessGrant: FlixyAccessGrant; RuntimeBinding: RuntimeBinding;
  CommandReceipt: CommandReceipt; EventSequence: EventSequence;
  VolumeRun: VolumeRun;
  AnalyticsBinding: AnalyticsBinding;
  OntologyBinding:OntologyBinding;
};
export const schema = [Content, Customer, Campaign, CampaignMember, IntegrationLink, Offer, Rental, Playback, Outbox,
  ControlCommand, OperatorGrant, FlixyAccessGrant, RuntimeBinding, CommandReceipt, EventSequence, VolumeRun, AnalyticsBinding,OntologyBinding];
