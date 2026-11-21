package com.salgu.backend.repository;

import com.salgu.backend.domain.SubwayTimetable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface SubwayTimetableRepository extends JpaRepository<SubwayTimetable, Long> {
}
