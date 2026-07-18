-- public.traffic_events_aggregated definition

-- Drop table

-- DROP TABLE public.traffic_events_aggregated;

CREATE TABLE public.traffic_events_aggregated (
	id bigserial NOT NULL,
	source_id varchar(20) NOT NULL,
	vehicle_type varchar(20) NOT NULL,
	window_start timestamp NOT NULL,
	window_end timestamp NOT NULL,
	total_count int4 DEFAULT 0 NULL,
	avg_speed numeric(6, 2) NULL,
	max_speed numeric(6, 2) NULL,
	min_speed numeric(6, 2) NULL,
	avg_confidence numeric(4, 3) NULL,
	traffic_status varchar(20) NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT traffic_events_aggregated_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_agg_source ON public.traffic_events_aggregated USING btree (source_id);
CREATE INDEX idx_agg_time ON public.traffic_events_aggregated USING btree (window_start DESC);

-- public.rep_traffic_summary_5min definition

-- Drop table

-- DROP TABLE public.rep_traffic_summary_5min;

CREATE TABLE public.rep_traffic_summary_5min (
	id serial4 NOT NULL,
	window_start timestamp NOT NULL,
	window_end timestamp NOT NULL,
	source_id varchar(50) NOT NULL,
	total_vehicles int4 DEFAULT 0 NOT NULL,
	avg_speed_kmh float8 NULL,
	created_at timestamp DEFAULT now() NOT NULL,
	CONSTRAINT rep_traffic_summary_5min_pkey PRIMARY KEY (id),
	CONSTRAINT uq_rep_traffic_summary_window UNIQUE (window_start, source_id)
);

-- public.rep_traffic_summary_5min_by_type definition

-- Drop table

-- DROP TABLE public.rep_traffic_summary_5min_by_type;

CREATE TABLE public.rep_traffic_summary_5min_by_type (
	id serial4 NOT NULL,
	window_start timestamp NOT NULL,
	window_end timestamp NOT NULL,
	source_id varchar(50) NOT NULL,
	vehicle_type varchar(50) NOT NULL,
	vehicle_count int4 DEFAULT 0 NOT NULL,
	avg_speed_kmh float8 NULL,
	created_at timestamp DEFAULT now() NOT NULL,
	CONSTRAINT rep_traffic_summary_5min_by_type_pkey PRIMARY KEY (id),
	CONSTRAINT uq_rep_traffic_summary_type_window UNIQUE (window_start, source_id, vehicle_type)
);