#![forbid(unsafe_code)]
#![deny(missing_docs)]

//! Public persistence contract for the Agent Pontifex bridge.
//!
//! The service uses explicit, parameterized SeaORM statements for operations
//! whose PostgreSQL semantics should not be approximated by generated CRUD.
//! These entity names provide a typed, public ownership boundary for the five
//! tables in [`SCHEMA_SQL`].

/// The desired-state PostgreSQL schema consumed by DPM.
pub const SCHEMA_SQL: &str = include_str!("../schema.sql");

/// The machine-readable ownership and migration contract.
pub const CONTRACT_JSON: &str = include_str!("../contract.json");

macro_rules! entity_name {
    ($name:ident, $table:literal, $docs:literal) => {
        #[doc = $docs]
        #[derive(Clone, Copy, Debug, Default)]
        pub struct $name;

        impl sea_orm::sea_query::Iden for $name {
            fn unquoted(&self, output: &mut dyn std::fmt::Write) {
                output
                    .write_str($table)
                    .expect("writing a static table identifier cannot fail");
            }
        }

        impl sea_orm::IdenStatic for $name {
            fn as_str(&self) -> &str {
                $table
            }
        }

        impl sea_orm::EntityName for $name {
            fn schema_name(&self) -> Option<&str> {
                Some("ai_agent_bridge")
            }

            fn table_name(&self) -> &str {
                $table
            }
        }
    };
}

entity_name!(AgentsEntity, "agents", "Agent identity and durable metadata table.");
entity_name!(
    ChannelsEntity,
    "channels",
    "Durable topic and embedding metadata table."
);
entity_name!(
    ChannelMembersEntity,
    "channel_members",
    "Best-effort channel membership mirror table."
);
entity_name!(MessagesEntity, "messages", "Ordered durable message history table.");
entity_name!(
    SharedContextEntity,
    "shared_context",
    "Optimistically versioned shared context table."
);

#[cfg(test)]
mod tests {
    use super::*;
    use sea_orm::EntityName;

    #[test]
    fn public_entities_name_only_the_bridge_schema() {
        let names = [
            (AgentsEntity.schema_name(), AgentsEntity.table_name()),
            (ChannelsEntity.schema_name(), ChannelsEntity.table_name()),
            (
                ChannelMembersEntity.schema_name(),
                ChannelMembersEntity.table_name(),
            ),
            (MessagesEntity.schema_name(), MessagesEntity.table_name()),
            (
                SharedContextEntity.schema_name(),
                SharedContextEntity.table_name(),
            ),
        ];

        assert_eq!(
            names,
            [
                (Some("ai_agent_bridge"), "agents"),
                (Some("ai_agent_bridge"), "channels"),
                (Some("ai_agent_bridge"), "channel_members"),
                (Some("ai_agent_bridge"), "messages"),
                (Some("ai_agent_bridge"), "shared_context"),
            ]
        );
    }

    #[test]
    fn embedded_contract_names_every_entity_table() {
        for table in [
            "agents",
            "channels",
            "channel_members",
            "messages",
            "shared_context",
        ] {
            assert!(
                SCHEMA_SQL.contains(&format!("ai_agent_bridge.{table}")),
                "schema is missing {table}"
            );
        }
        assert!(CONTRACT_JSON.contains("\"privateCheckoutRequired\": false"));
    }
}
