package com.salgu.backend.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Immutable;

@Getter
@Entity
@Immutable
@Table(name = "bus_stops")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class BusStop extends SourceRowEntity {

    private String nodeId;

    private String arsId;

    private String stopName;

    private BigDecimal longitude;

    private BigDecimal latitude;

    private String stopType;
}
