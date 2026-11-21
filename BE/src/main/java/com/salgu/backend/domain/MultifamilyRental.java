package com.salgu.backend.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.Immutable;

@Getter
@Entity
@Immutable
@Table(name = "multifamily_rentals")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class MultifamilyRental extends RentalTransaction {

    private String housingType;
}
