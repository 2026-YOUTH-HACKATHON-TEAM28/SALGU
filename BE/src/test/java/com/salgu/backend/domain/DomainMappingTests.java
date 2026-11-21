package com.salgu.backend.domain;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** Column counts per table must match the DB spec (common 3 columns included). */
@SpringBootTest
@ActiveProfiles("test")
class DomainMappingTests {

    private static final Map<String, Integer> SPEC_COLUMN_COUNTS = Map.ofEntries(
            Map.entry("bus_route_stops", 11),
            Map.entry("bus_routes", 19),
            Map.entry("bus_stops", 9),
            Map.entry("housing_policies", 65),
            Map.entry("legal_dongs", 6),
            Map.entry("multifamily_rentals", 25),
            Map.entry("officetel_rentals", 24),
            Map.entry("real_estate_agencies", 22),
            Map.entry("subway_first_last", 22),
            Map.entry("subway_stations", 11),
            Map.entry("subway_timetables", 18));

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    void entityColumnsMatchSpec() {
        SPEC_COLUMN_COUNTS.forEach((table, expected) -> {
            Integer actual = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ?", Integer.class, table);
            assertThat(actual).as(table).isEqualTo(expected);
        });
    }
}
